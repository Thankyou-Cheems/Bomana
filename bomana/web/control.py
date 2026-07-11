"""Schema-backed immutable control messages for the Bomana Web Cockpit.

This module deliberately has no UI or configuration dependencies.  The HTTP
runtime validates untrusted JSON here, while the Tk owner consumes the frozen
semantic command types and publishes frozen control projections.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from bomana.utils.file_utils import resource_path

COMMAND_SCHEMA_NAME = "web-dashboard-command.schema.json"
COMMAND_RESPONSE_SCHEMA_NAME = "web-dashboard-command-response.schema.json"
CONTROL_STATE_SCHEMA_NAME = "web-dashboard-control-state.schema.json"

COMMAND_NAMES = (
    "action.reset_timer",
    "action.cycle_corner",
    "state.set_locked",
    "state.set_beep_enabled",
    "state.set_zone_sound_enabled",
    "config.set_panel_visibility",
    "weapon.select",
    "weapon.set_ballistic_model",
)
PANEL_TARGETS = (
    "zones",
    "airfields",
    "fuel",
    "speed",
    "checklist",
    "weapon_solution",
)
BALLISTIC_MODELS = ("foxthree_compatible", "strict_official")
COMPLETION_REASONS = (
    "ok",
    "authorization_revoked",
    "feature_disabled",
    "invalid_target",
    "weapon_not_found",
    "weapon_incompatible",
    "state_unavailable",
    "persistence_failed",
    "execution_failed",
)

type CommandName = Literal[
    "action.reset_timer",
    "action.cycle_corner",
    "state.set_locked",
    "state.set_beep_enabled",
    "state.set_zone_sound_enabled",
    "config.set_panel_visibility",
    "weapon.select",
    "weapon.set_ballistic_model",
]
type PanelTarget = Literal["zones", "airfields", "fuel", "speed", "checklist", "weapon_solution"]
type BallisticModel = Literal["foxthree_compatible", "strict_official"]
type Transport = Literal["loopback", "lan"]
type ControlScope = Literal["view", "control"]
type CompletionStatus = Literal["succeeded", "rejected"]
type CompletionReason = Literal[
    "ok",
    "authorization_revoked",
    "feature_disabled",
    "invalid_target",
    "weapon_not_found",
    "weapon_incompatible",
    "state_unavailable",
    "persistence_failed",
    "execution_failed",
]


class ControlValidationError(ValueError):
    """Raised when a Web control payload does not satisfy its shared schema."""


def _schema_root() -> Path:
    return Path(resource_path("docs/specs/schemas"))


def _load_schema(name: str) -> Mapping[str, Any]:
    path = _schema_root() / name
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"unable to load Web control schema: {name}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"invalid Web control schema root: {name}")
    return MappingProxyType(value)


_SCHEMAS = MappingProxyType(
    {
        COMMAND_SCHEMA_NAME: _load_schema(COMMAND_SCHEMA_NAME),
        COMMAND_RESPONSE_SCHEMA_NAME: _load_schema(COMMAND_RESPONSE_SCHEMA_NAME),
        CONTROL_STATE_SCHEMA_NAME: _load_schema(CONTROL_STATE_SCHEMA_NAME),
    }
)


def _json_type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def _json_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    if left is None or right is None:
        return left is right
    return left == right


def _schema_valid(value: Any, schema: Mapping[str, Any], root: Mapping[str, Any]) -> bool:
    reference = schema.get("$ref")
    if reference is not None:
        prefix = "#/$defs/"
        if not isinstance(reference, str) or not reference.startswith(prefix):
            return False
        definition = root.get("$defs", {}).get(reference.removeprefix(prefix))
        return isinstance(definition, dict) and _schema_valid(value, definition, root)

    branches = schema.get("oneOf")
    if branches is not None:
        if not isinstance(branches, list):
            return False
        if (
            sum(
                1
                for branch in branches
                if isinstance(branch, dict) and _schema_valid(value, branch, root)
            )
            != 1
        ):
            return False

    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _json_type_matches(value, expected_type):
        return False
    if "const" in schema and not _json_equal(value, schema["const"]):
        return False
    allowed = schema.get("enum")
    if isinstance(allowed, list) and not any(_json_equal(value, item) for item in allowed):
        return False

    if isinstance(value, dict):
        required = schema.get("required", [])
        if not isinstance(required, list) or any(name not in value for name in required):
            return False
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return False
        if schema.get("additionalProperties") is False and any(
            name not in properties for name in value
        ):
            return False
        for name, child in value.items():
            child_schema = properties.get(name)
            if isinstance(child_schema, dict) and not _schema_valid(child, child_schema, root):
                return False

    if isinstance(value, list):
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            return False
        if isinstance(maximum, int) and len(value) > maximum:
            return False
        if schema.get("uniqueItems") and len(
            {json.dumps(item, sort_keys=True) for item in value}
        ) != len(value):
            return False
        item_schema = schema.get("items")
        if isinstance(item_schema, dict) and any(
            not _schema_valid(item, item_schema, root) for item in value
        ):
            return False

    if isinstance(value, str):
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        pattern = schema.get("pattern")
        if isinstance(minimum, int) and len(value) < minimum:
            return False
        if isinstance(maximum, int) and len(value) > maximum:
            return False
        if isinstance(pattern, str) and re.fullmatch(pattern, value) is None:
            return False

    if isinstance(value, int | float) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, int | float) and value < minimum:
            return False
        if isinstance(maximum, int | float) and value > maximum:
            return False

    all_of = schema.get("allOf", [])
    if not isinstance(all_of, list) or any(
        not isinstance(child, dict) or not _schema_valid(value, child, root) for child in all_of
    ):
        return False
    condition = schema.get("if")
    if isinstance(condition, dict):
        branch_name = "then" if _schema_valid(value, condition, root) else "else"
        branch = schema.get(branch_name)
        if isinstance(branch, dict) and not _schema_valid(value, branch, root):
            return False
    return True


def validate_schema_payload(name: str, payload: Any) -> None:
    """Validate a value against one of the three packaged Web control schemas."""

    schema = _SCHEMAS.get(name)
    if schema is None or not _schema_valid(payload, schema, schema):
        raise ControlValidationError(f"payload does not match {name}")


@dataclass(frozen=True)
class ValidatedWebCommand:
    """One exact command from the canonical eight-action matrix."""

    name: CommandName
    confirmed: bool | None = None
    locked: bool | None = None
    enabled: bool | None = None
    target: PanelTarget | None = None
    weapon_id: str | None = None
    model: BallisticModel | None = None

    def __post_init__(self) -> None:
        fields = (
            self.confirmed,
            self.locked,
            self.enabled,
            self.target,
            self.weapon_id,
            self.model,
        )
        expected: tuple[Any, ...]
        if self.name == "action.reset_timer":
            expected = (True, None, None, None, None, None)
        elif self.name == "action.cycle_corner":
            expected = (None, None, None, None, None, None)
        elif self.name == "state.set_locked" and isinstance(self.locked, bool):
            expected = (None, self.locked, None, None, None, None)
        elif self.name in ("state.set_beep_enabled", "state.set_zone_sound_enabled") and isinstance(
            self.enabled, bool
        ):
            expected = (None, None, self.enabled, None, None, None)
        elif (
            self.name == "config.set_panel_visibility"
            and self.target in PANEL_TARGETS
            and isinstance(self.enabled, bool)
        ):
            expected = (None, None, self.enabled, self.target, None, None)
        elif (
            self.name == "weapon.select"
            and isinstance(self.weapon_id, str)
            and 1 <= len(self.weapon_id) <= 128
        ):
            expected = (None, None, None, None, self.weapon_id, None)
        elif self.name == "weapon.set_ballistic_model" and self.model in BALLISTIC_MODELS:
            expected = (None, None, None, None, None, self.model)
        else:
            raise ControlValidationError("invalid semantic command fields")
        if fields != expected:
            raise ControlValidationError("unexpected semantic command fields")

    def as_payload(self) -> dict[str, bool | int | str]:
        payload: dict[str, bool | int | str] = {"schema_version": 1, "command": self.name}
        if self.name == "action.reset_timer":
            payload["confirmed"] = True
        elif self.name == "state.set_locked":
            payload["locked"] = bool(self.locked)
        elif self.name in ("state.set_beep_enabled", "state.set_zone_sound_enabled"):
            payload["enabled"] = bool(self.enabled)
        elif self.name == "config.set_panel_visibility":
            payload["target"] = str(self.target)
            payload["enabled"] = bool(self.enabled)
        elif self.name == "weapon.select":
            payload["weapon_id"] = str(self.weapon_id)
        elif self.name == "weapon.set_ballistic_model":
            payload["model"] = str(self.model)
        return payload

    @property
    def canonical_json(self) -> str:
        return json.dumps(
            self.as_payload(), ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )


def validate_command_payload(payload: Any) -> ValidatedWebCommand:
    """Validate untrusted JSON and return a frozen explicit semantic command."""

    validate_schema_payload(COMMAND_SCHEMA_NAME, payload)
    assert isinstance(payload, dict)  # Proved by the production-loaded schema.
    name = payload["command"]
    if name == "action.reset_timer":
        return ValidatedWebCommand(name=name, confirmed=True)
    if name == "action.cycle_corner":
        return ValidatedWebCommand(name=name)
    if name == "state.set_locked":
        return ValidatedWebCommand(name=name, locked=payload["locked"])
    if name == "state.set_beep_enabled":
        return ValidatedWebCommand(name=name, enabled=payload["enabled"])
    if name == "state.set_zone_sound_enabled":
        return ValidatedWebCommand(name=name, enabled=payload["enabled"])
    if name == "config.set_panel_visibility":
        return ValidatedWebCommand(
            name=name,
            target=payload["target"],
            enabled=payload["enabled"],
        )
    if name == "weapon.select":
        return ValidatedWebCommand(name=name, weapon_id=payload["weapon_id"])
    if name == "weapon.set_ballistic_model":
        return ValidatedWebCommand(name=name, model=payload["model"])
    raise ControlValidationError("command is outside the action matrix")


@dataclass(frozen=True)
class WebCommandEnvelope:
    """Immutable HTTP-to-Tk command handoff."""

    session_token: str = field(repr=False)
    transport: Transport
    scope: ControlScope
    authorization_epoch: int
    command_id: str = field(repr=False)
    command: ValidatedWebCommand = field(repr=False)
    submitted_revision: int


@dataclass(frozen=True)
class PanelVisibility:
    zones: bool
    airfields: bool
    fuel: bool
    speed: bool
    checklist: bool
    weapon_solution: bool

    def as_payload(self) -> dict[str, bool]:
        return {
            "zones": self.zones,
            "airfields": self.airfields,
            "fuel": self.fuel,
            "speed": self.speed,
            "checklist": self.checklist,
            "weapon_solution": self.weapon_solution,
        }


@dataclass(frozen=True)
class ControlTargetState:
    locked: bool
    beep_enabled: bool
    zone_sound_enabled: bool
    panel_visibility: PanelVisibility
    selected_weapon_id: str
    ballistic_model: BallisticModel

    def as_payload(self) -> dict[str, Any]:
        return {
            "locked": self.locked,
            "beep_enabled": self.beep_enabled,
            "zone_sound_enabled": self.zone_sound_enabled,
            "panel_visibility": self.panel_visibility.as_payload(),
            "selected_weapon_id": self.selected_weapon_id,
            "ballistic_model": self.ballistic_model,
        }


@dataclass(frozen=True)
class WeaponChoice:
    weapon_id: str
    display_name: str
    role: str
    compatible: bool
    selected: bool

    def as_payload(self) -> dict[str, Any]:
        return {
            "weapon_id": self.weapon_id,
            "display_name": self.display_name,
            "role": self.role,
            "compatible": self.compatible,
            "selected": self.selected,
        }


@dataclass(frozen=True)
class ControlStateProjection:
    """App-owned immutable state shared with HTTP workers."""

    revision: int
    commands: tuple[CommandName, ...]
    panel_targets: tuple[PanelTarget, ...]
    state: ControlTargetState
    weapons: tuple[WeaponChoice, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.commands, tuple) or not isinstance(self.panel_targets, tuple):
            raise ControlValidationError("control capabilities must be immutable tuples")
        if not isinstance(self.weapons, tuple):
            raise ControlValidationError("weapon choices must be an immutable tuple")
        if not isinstance(self.state, ControlTargetState):
            raise ControlValidationError("control target state has the wrong type")
        if any(not isinstance(weapon, WeaponChoice) for weapon in self.weapons):
            raise ControlValidationError("weapon choice has the wrong type")

    def base_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "revision": self.revision,
            "capabilities": {
                "commands": list(self.commands),
                "panel_targets": list(self.panel_targets),
            },
            "state": self.state.as_payload(),
            "weapons": [weapon.as_payload() for weapon in self.weapons],
        }


class DashboardControlStore:
    """Thread-safe immutable App-to-HTTP control-state projection store."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: ControlStateProjection | None = None
        self._canonical: str | None = None

    def publish(self, projection: ControlStateProjection) -> None:
        if not isinstance(projection, ControlStateProjection):
            raise TypeError("projection must be ControlStateProjection")
        payload = {
            **projection.base_payload(),
            "permissions": {
                "scope": "control",
                "transport": "loopback",
                "control_epoch": 0,
                "lan_control_enabled": False,
            },
            "csrf": "x" * 43,
            "recent_commands": [],
        }
        validate_schema_payload(CONTROL_STATE_SCHEMA_NAME, payload)
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._lock:
            previous = self._latest
            if previous is not None and projection.revision < previous.revision:
                raise ControlValidationError("control-state revision regressed")
            if (
                previous is not None
                and projection.revision == previous.revision
                and canonical != self._canonical
            ):
                raise ControlValidationError("control state changed without a revision advance")
            self._latest = projection
            self._canonical = canonical

    def read(self) -> ControlStateProjection | None:
        with self._lock:
            return self._latest


def build_control_state_payload(
    projection: ControlStateProjection,
    *,
    scope: ControlScope,
    transport: Transport,
    authorization_epoch: int,
    lan_control_enabled: bool,
    csrf: str | None,
    recent_commands: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Add session-owned authority and bounded history to an App projection."""

    can_control = scope == "control"
    payload = {
        **projection.base_payload(),
        "permissions": {
            "scope": scope,
            "transport": transport,
            "control_epoch": authorization_epoch,
            "lan_control_enabled": bool(lan_control_enabled),
        },
        "csrf": csrf if can_control else None,
        "capabilities": {
            "commands": list(projection.commands) if can_control else [],
            "panel_targets": list(projection.panel_targets) if can_control else [],
        },
        "recent_commands": [dict(item) for item in recent_commands] if can_control else [],
    }
    validate_schema_payload(CONTROL_STATE_SCHEMA_NAME, payload)
    return payload


def validate_command_response(payload: Mapping[str, Any]) -> None:
    validate_schema_payload(COMMAND_RESPONSE_SCHEMA_NAME, dict(payload))
