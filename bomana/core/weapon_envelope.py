"""Pure interpolation for Datamine guided-weapon launch envelopes.

The source tables store two target-motion cells per fighter-Mach row.  The
even cell uses the signed ``target_mach`` endpoint and the odd cell uses that
endpoint multiplied by ``target_mach2_mult``.  Some legacy tables store the
head-on (negative) endpoint first, so endpoint labels derive from sign rather
than array position.

All axes clamp at their nearest endpoint.  Invalid shapes and unavailable
cells produce machine-readable results instead of exceptions crossing into
the scheduler.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

STATUS_AVAILABLE = "available"
STATUS_UNAVAILABLE = "unavailable"

REASON_OK = "ok"
REASON_INVALID_INPUT = "invalid_input"
REASON_MISSING_TABLES = "missing_tables"
REASON_INVALID_SHAPE = "invalid_shape"
REASON_INVALID_AXIS = "invalid_axis"
REASON_UNSUPPORTED_FIELD = "unsupported_field"
REASON_MISSING_FIELD = "missing_field"
REASON_UNAVAILABLE_CELL = "unavailable_cell"
REASON_ENDPOINT_UNAVAILABLE = "endpoint_unavailable"

FIELD_RANGE_MIN_M = "range_min_m"
FIELD_RANGE_MAX_M = "range_max_m"
FIELD_RANGE_MIN_DOGFIGHT_M = "range_min_dogfight_m"
FIELD_RANGE_MAX_DOGFIGHT_M = "range_max_dogfight_m"
FIELD_TIME_MAX_S = "time_max_s"

SUPPORTED_FIELDS = frozenset(
    {
        FIELD_RANGE_MIN_M,
        FIELD_RANGE_MAX_M,
        FIELD_RANGE_MIN_DOGFIGHT_M,
        FIELD_RANGE_MAX_DOGFIGHT_M,
        FIELD_TIME_MAX_S,
    }
)


@dataclass(frozen=True, slots=True)
class EnvelopeValue:
    """One interpolated value or a machine-readable unavailable result."""

    available: bool = False
    value: float | None = None
    status: str = STATUS_UNAVAILABLE
    reason: str = REASON_INVALID_INPUT


@dataclass(frozen=True, slots=True)
class EnvelopeEndpoint:
    """One target-motion endpoint, including its interpolated signed Mach."""

    available: bool = False
    value: float | None = None
    target_radial_mach: float | None = None
    status: str = STATUS_UNAVAILABLE
    reason: str = REASON_INVALID_INPUT


@dataclass(frozen=True, slots=True)
class AspectEnvelope:
    """Tail-chase and head-on endpoints at one launch condition."""

    tail_chase: EnvelopeEndpoint
    head_on: EnvelopeEndpoint
    available: bool = False
    status: str = STATUS_UNAVAILABLE
    reason: str = REASON_ENDPOINT_UNAVAILABLE


class _EnvelopeUnavailable(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _unavailable(reason: str) -> EnvelopeValue:
    return EnvelopeValue(status=STATUS_UNAVAILABLE, reason=reason)


def _available(value: float) -> EnvelopeValue:
    return EnvelopeValue(
        available=True,
        value=value,
        status=STATUS_AVAILABLE,
        reason=REASON_OK,
    )


def _endpoint_unavailable(reason: str) -> EnvelopeEndpoint:
    return EnvelopeEndpoint(status=STATUS_UNAVAILABLE, reason=reason)


def _endpoint_available(value: float, target_radial_mach: float) -> EnvelopeEndpoint:
    return EnvelopeEndpoint(
        available=True,
        value=value,
        target_radial_mach=target_radial_mach,
        status=STATUS_AVAILABLE,
        reason=REASON_OK,
    )


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray)


def _finite_number(value: Any, reason: str) -> float:
    if isinstance(value, bool):
        raise _EnvelopeUnavailable(reason)
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _EnvelopeUnavailable(reason) from exc
    if not math.isfinite(number):
        raise _EnvelopeUnavailable(reason)
    return number


def _strict_axis(raw_axis: Any) -> list[float]:
    if not _is_sequence(raw_axis) or len(raw_axis) != 2:
        raise _EnvelopeUnavailable(REASON_INVALID_SHAPE)
    axis = [_finite_number(item, REASON_INVALID_AXIS) for item in raw_axis]
    pairs = list(zip(axis, axis[1:], strict=False))
    increasing = all(right > left for left, right in pairs)
    decreasing = all(right < left for left, right in pairs)
    if not (increasing or decreasing):
        raise _EnvelopeUnavailable(REASON_INVALID_AXIS)
    return axis


def _bracket(axis: Sequence[float], value: float) -> tuple[int, int, float]:
    """Return clamped lower/upper indices and an interpolation fraction."""

    minimum = min(axis)
    maximum = max(axis)
    if value <= minimum:
        index = axis.index(minimum)
        return index, index, 0.0
    if value >= maximum:
        index = axis.index(maximum)
        return index, index, 0.0

    for first in range(len(axis) - 1):
        second = first + 1
        first_value = axis[first]
        second_value = axis[second]
        if min(first_value, second_value) <= value <= max(first_value, second_value):
            if value == first_value:
                return first, first, 0.0
            if value == second_value:
                return second, second, 0.0
            fraction = (value - first_value) / (second_value - first_value)
            return first, second, fraction
    raise _EnvelopeUnavailable(REASON_INVALID_AXIS)


def _lerp(lower: float, upper: float, fraction: float) -> float:
    if fraction <= 0.0 or lower == upper:
        return lower
    return lower + (upper - lower) * fraction


def _prepare_tables(envelope: Mapping[str, Any] | None) -> list[tuple[float, Mapping[str, Any]]]:
    if not isinstance(envelope, Mapping):
        raise _EnvelopeUnavailable(REASON_MISSING_TABLES)
    raw_tables = envelope.get("tables")
    if not _is_sequence(raw_tables) or not raw_tables:
        raise _EnvelopeUnavailable(REASON_MISSING_TABLES)

    tables: list[tuple[float, Mapping[str, Any]]] = []
    for raw_table in raw_tables:
        if not isinstance(raw_table, Mapping):
            raise _EnvelopeUnavailable(REASON_INVALID_SHAPE)
        altitude = _finite_number(raw_table.get("altitude_m"), REASON_INVALID_AXIS)
        tables.append((altitude, raw_table))
    tables.sort(key=lambda item: item[0])
    if any(right[0] <= left[0] for left, right in zip(tables, tables[1:], strict=False)):
        raise _EnvelopeUnavailable(REASON_INVALID_AXIS)
    return tables


def _table_context(
    table: Mapping[str, Any], field: str
) -> tuple[list[float], list[float], float, Sequence[Any]]:
    fighter_mach = _strict_axis(table.get("fighter_mach"))
    raw_target_mach = table.get("target_mach")
    if not _is_sequence(raw_target_mach) or len(raw_target_mach) != len(fighter_mach):
        raise _EnvelopeUnavailable(REASON_INVALID_SHAPE)
    target_mach = [_finite_number(item, REASON_INVALID_AXIS) for item in raw_target_mach]
    if any(item == 0.0 for item in target_mach):
        raise _EnvelopeUnavailable(REASON_INVALID_AXIS)

    target_mach2_mult = _finite_number(table.get("target_mach2_mult"), REASON_INVALID_AXIS)
    if target_mach2_mult >= 0.0:
        raise _EnvelopeUnavailable(REASON_INVALID_AXIS)

    if field not in table:
        raise _EnvelopeUnavailable(REASON_MISSING_FIELD)
    cells = table[field]
    if not _is_sequence(cells) or len(cells) != 2 * len(fighter_mach):
        raise _EnvelopeUnavailable(REASON_INVALID_SHAPE)
    return fighter_mach, target_mach, target_mach2_mult, cells


def _cell(cells: Sequence[Any], index: int) -> float:
    value = _finite_number(cells[index], REASON_UNAVAILABLE_CELL)
    if value <= 0.0:
        raise _EnvelopeUnavailable(REASON_UNAVAILABLE_CELL)
    return value


def _row_value(
    cells: Sequence[Any],
    row: int,
    *,
    target_mach: float,
    target_mach2_mult: float,
    target_radial_mach: float,
) -> float:
    first_endpoint = target_mach
    second_endpoint = target_mach * target_mach2_mult
    lower_endpoint = min(first_endpoint, second_endpoint)
    upper_endpoint = max(first_endpoint, second_endpoint)
    if lower_endpoint >= 0.0 or upper_endpoint <= 0.0:
        raise _EnvelopeUnavailable(REASON_INVALID_AXIS)
    if target_radial_mach <= lower_endpoint:
        index = 2 * row if first_endpoint == lower_endpoint else 2 * row + 1
        return _cell(cells, index)
    if target_radial_mach >= upper_endpoint:
        index = 2 * row if first_endpoint == upper_endpoint else 2 * row + 1
        return _cell(cells, index)

    first_value = _cell(cells, 2 * row)
    second_value = _cell(cells, 2 * row + 1)
    fraction = (target_radial_mach - first_endpoint) / (second_endpoint - first_endpoint)
    return _lerp(first_value, second_value, fraction)


def _table_value(
    table: Mapping[str, Any],
    *,
    field: str,
    fighter_mach_value: float,
    row_target_radial_mach: Callable[[float, float], float],
) -> float:
    fighter_axis, target_axis, target_mult, cells = _table_context(table, field)
    lower, upper, fraction = _bracket(fighter_axis, fighter_mach_value)

    def evaluate(row: int) -> float:
        target_mach = target_axis[row]
        target_radial_mach = row_target_radial_mach(target_mach, target_mult)
        return _row_value(
            cells,
            row,
            target_mach=target_mach,
            target_mach2_mult=target_mult,
            target_radial_mach=target_radial_mach,
        )

    lower_value = evaluate(lower)
    if lower == upper:
        return lower_value
    return _lerp(lower_value, evaluate(upper), fraction)


def _over_altitude(
    tables: Sequence[tuple[float, Mapping[str, Any]]],
    *,
    altitude_m: float,
    evaluate: Callable[[Mapping[str, Any]], float],
) -> float:
    altitude_axis = [item[0] for item in tables]
    lower, upper, fraction = _bracket(altitude_axis, altitude_m)
    lower_value = evaluate(tables[lower][1])
    if lower == upper:
        return lower_value
    return _lerp(lower_value, evaluate(tables[upper][1]), fraction)


def _validate_field(field: Any) -> str:
    if not isinstance(field, str) or field not in SUPPORTED_FIELDS:
        raise _EnvelopeUnavailable(REASON_UNSUPPORTED_FIELD)
    return field


def interpolate_envelope(
    envelope: Mapping[str, Any] | None,
    *,
    field: str,
    altitude_m: float,
    fighter_mach: float,
    target_radial_mach: float,
) -> EnvelopeValue:
    """Interpolate one field for a known signed target radial Mach.

    Positive target radial Mach means the target moves away along line of
    sight; negative means it closes.  Target motion is interpolated first in
    each fighter row, followed by fighter Mach and then launch altitude.
    """

    try:
        field = _validate_field(field)
        altitude = _finite_number(altitude_m, REASON_INVALID_INPUT)
        fighter = _finite_number(fighter_mach, REASON_INVALID_INPUT)
        target_radial = _finite_number(target_radial_mach, REASON_INVALID_INPUT)
        tables = _prepare_tables(envelope)
        value = _over_altitude(
            tables,
            altitude_m=altitude,
            evaluate=lambda table: _table_value(
                table,
                field=field,
                fighter_mach_value=fighter,
                row_target_radial_mach=lambda _target_mach, _mult: target_radial,
            ),
        )
    except _EnvelopeUnavailable as exc:
        return _unavailable(exc.reason)
    except IndexError, KeyError, TypeError, ValueError, OverflowError:
        return _unavailable(REASON_INVALID_SHAPE)
    return _available(value)


def interpolate_aspect(
    envelope: Mapping[str, Any] | None,
    *,
    field: str,
    altitude_m: float,
    fighter_mach: float,
    aspect_cosine: float,
) -> EnvelopeValue:
    """Interpolate by geometry when target speed is not available.

    ``aspect_cosine`` is clamped to ``[-1, 1]``: ``+1`` is the target-away
    (tail-chase) endpoint, ``-1`` is the closing (head-on) endpoint, and zero
    is side-on.  Each fighter row maps that geometry to its own target-Mach
    endpoints before any fighter-Mach or altitude interpolation occurs.
    """

    try:
        field = _validate_field(field)
        altitude = _finite_number(altitude_m, REASON_INVALID_INPUT)
        fighter = _finite_number(fighter_mach, REASON_INVALID_INPUT)
        cosine = max(-1.0, min(1.0, _finite_number(aspect_cosine, REASON_INVALID_INPUT)))
        tables = _prepare_tables(envelope)

        def for_row(target_mach: float, target_mult: float) -> float:
            first_endpoint = target_mach
            second_endpoint = target_mach * target_mult
            positive_endpoint = max(first_endpoint, second_endpoint)
            negative_endpoint = min(first_endpoint, second_endpoint)
            if negative_endpoint >= 0.0 or positive_endpoint <= 0.0:
                raise _EnvelopeUnavailable(REASON_INVALID_AXIS)
            if cosine >= 0.0:
                return cosine * positive_endpoint
            return (-cosine) * negative_endpoint

        value = _over_altitude(
            tables,
            altitude_m=altitude,
            evaluate=lambda table: _table_value(
                table,
                field=field,
                fighter_mach_value=fighter,
                row_target_radial_mach=for_row,
            ),
        )
    except _EnvelopeUnavailable as exc:
        return _unavailable(exc.reason)
    except IndexError, KeyError, TypeError, ValueError, OverflowError:
        return _unavailable(REASON_INVALID_SHAPE)
    return _available(value)


def _table_endpoint(
    table: Mapping[str, Any],
    *,
    field: str,
    fighter_mach_value: float,
    positive: bool,
) -> tuple[float, float]:
    fighter_axis, target_axis, target_mult, cells = _table_context(table, field)
    lower, upper, fraction = _bracket(fighter_axis, fighter_mach_value)

    def evaluate(row: int) -> tuple[float, float]:
        first_endpoint = target_axis[row]
        second_endpoint = target_axis[row] * target_mult
        if first_endpoint == second_endpoint or first_endpoint * second_endpoint >= 0.0:
            raise _EnvelopeUnavailable(REASON_INVALID_AXIS)
        if positive == (first_endpoint > second_endpoint):
            return _cell(cells, 2 * row), first_endpoint
        return _cell(cells, 2 * row + 1), second_endpoint

    lower_value, lower_target = evaluate(lower)
    if lower == upper:
        return lower_value, lower_target
    upper_value, upper_target = evaluate(upper)
    return (
        _lerp(lower_value, upper_value, fraction),
        _lerp(lower_target, upper_target, fraction),
    )


def _endpoint_over_altitude(
    tables: Sequence[tuple[float, Mapping[str, Any]]],
    *,
    field: str,
    altitude_m: float,
    fighter_mach: float,
    positive: bool,
) -> tuple[float, float]:
    altitude_axis = [item[0] for item in tables]
    lower, upper, fraction = _bracket(altitude_axis, altitude_m)
    lower_value, lower_target = _table_endpoint(
        tables[lower][1],
        field=field,
        fighter_mach_value=fighter_mach,
        positive=positive,
    )
    if lower == upper:
        return lower_value, lower_target
    upper_value, upper_target = _table_endpoint(
        tables[upper][1],
        field=field,
        fighter_mach_value=fighter_mach,
        positive=positive,
    )
    return (
        _lerp(lower_value, upper_value, fraction),
        _lerp(lower_target, upper_target, fraction),
    )


def interpolate_aspect_endpoints(
    envelope: Mapping[str, Any] | None,
    *,
    field: str,
    altitude_m: float,
    fighter_mach: float,
) -> AspectEnvelope:
    """Return tail-chase and head-on values for one launch condition."""

    try:
        field = _validate_field(field)
        altitude = _finite_number(altitude_m, REASON_INVALID_INPUT)
        fighter = _finite_number(fighter_mach, REASON_INVALID_INPUT)
        tables = _prepare_tables(envelope)
    except _EnvelopeUnavailable as exc:
        unavailable = _endpoint_unavailable(exc.reason)
        return AspectEnvelope(
            tail_chase=unavailable,
            head_on=unavailable,
            reason=exc.reason,
        )
    except IndexError, KeyError, TypeError, ValueError, OverflowError:
        unavailable = _endpoint_unavailable(REASON_INVALID_SHAPE)
        return AspectEnvelope(
            tail_chase=unavailable,
            head_on=unavailable,
            reason=REASON_INVALID_SHAPE,
        )

    def endpoint(positive: bool) -> EnvelopeEndpoint:
        try:
            value, target_radial = _endpoint_over_altitude(
                tables,
                field=field,
                altitude_m=altitude,
                fighter_mach=fighter,
                positive=positive,
            )
        except _EnvelopeUnavailable as exc:
            return _endpoint_unavailable(exc.reason)
        except IndexError, KeyError, TypeError, ValueError, OverflowError:
            return _endpoint_unavailable(REASON_INVALID_SHAPE)
        return _endpoint_available(value, target_radial)

    tail_chase = endpoint(True)
    head_on = endpoint(False)
    if tail_chase.available and head_on.available:
        return AspectEnvelope(
            tail_chase=tail_chase,
            head_on=head_on,
            available=True,
            status=STATUS_AVAILABLE,
            reason=REASON_OK,
        )
    reason = (
        tail_chase.reason if tail_chase.reason == head_on.reason else REASON_ENDPOINT_UNAVAILABLE
    )
    return AspectEnvelope(tail_chase=tail_chase, head_on=head_on, reason=reason)


__all__ = [
    "FIELD_RANGE_MAX_DOGFIGHT_M",
    "FIELD_RANGE_MAX_M",
    "FIELD_RANGE_MIN_DOGFIGHT_M",
    "FIELD_RANGE_MIN_M",
    "FIELD_TIME_MAX_S",
    "REASON_ENDPOINT_UNAVAILABLE",
    "REASON_INVALID_AXIS",
    "REASON_INVALID_INPUT",
    "REASON_INVALID_SHAPE",
    "REASON_MISSING_FIELD",
    "REASON_MISSING_TABLES",
    "REASON_OK",
    "REASON_UNAVAILABLE_CELL",
    "REASON_UNSUPPORTED_FIELD",
    "STATUS_AVAILABLE",
    "STATUS_UNAVAILABLE",
    "SUPPORTED_FIELDS",
    "AspectEnvelope",
    "EnvelopeEndpoint",
    "EnvelopeValue",
    "interpolate_aspect",
    "interpolate_aspect_endpoints",
    "interpolate_envelope",
]
