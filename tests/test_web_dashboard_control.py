from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from bomana.web.control import (
    COMMAND_NAMES,
    COMMAND_RESPONSE_SCHEMA_NAME,
    CONTROL_STATE_SCHEMA_NAME,
    PANEL_TARGETS,
    ControlStateProjection,
    ControlTargetState,
    ControlValidationError,
    DashboardControlStore,
    PanelVisibility,
    ValidatedWebCommand,
    WeaponChoice,
    build_control_state_payload,
    validate_command_payload,
    validate_schema_payload,
)


def _projection(revision: int = 1) -> ControlStateProjection:
    return ControlStateProjection(
        revision=revision,
        commands=COMMAND_NAMES,
        panel_targets=PANEL_TARGETS,
        state=ControlTargetState(
            locked=False,
            beep_enabled=True,
            zone_sound_enabled=False,
            panel_visibility=PanelVisibility(
                zones=True,
                airfields=True,
                fuel=True,
                speed=True,
                checklist=True,
                weapon_solution=True,
            ),
            selected_weapon_id="aim_9l",
            ballistic_model="foxthree_compatible",
        ),
        weapons=(
            WeaponChoice(
                weapon_id="aim_9l",
                display_name="AIM-9L",
                role="air_to_air",
                compatible=True,
                selected=True,
            ),
        ),
    )


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {"schema_version": 1, "command": "action.reset_timer", "confirmed": True},
            ValidatedWebCommand(name="action.reset_timer", confirmed=True),
        ),
        (
            {"schema_version": 1, "command": "action.cycle_corner"},
            ValidatedWebCommand(name="action.cycle_corner"),
        ),
        (
            {"schema_version": 1, "command": "state.set_locked", "locked": True},
            ValidatedWebCommand(name="state.set_locked", locked=True),
        ),
        (
            {"schema_version": 1, "command": "state.set_beep_enabled", "enabled": False},
            ValidatedWebCommand(name="state.set_beep_enabled", enabled=False),
        ),
        (
            {
                "schema_version": 1,
                "command": "state.set_zone_sound_enabled",
                "enabled": True,
            },
            ValidatedWebCommand(name="state.set_zone_sound_enabled", enabled=True),
        ),
        (
            {
                "schema_version": 1,
                "command": "config.set_panel_visibility",
                "target": "fuel",
                "enabled": False,
            },
            ValidatedWebCommand(name="config.set_panel_visibility", target="fuel", enabled=False),
        ),
        (
            {"schema_version": 1, "command": "weapon.select", "weapon_id": "aim_9l"},
            ValidatedWebCommand(name="weapon.select", weapon_id="aim_9l"),
        ),
        (
            {
                "schema_version": 1,
                "command": "weapon.set_ballistic_model",
                "model": "strict_official",
            },
            ValidatedWebCommand(name="weapon.set_ballistic_model", model="strict_official"),
        ),
    ],
)
def test_exact_command_matrix_builds_frozen_semantic_commands(payload, expected) -> None:
    command = validate_command_payload(payload)

    assert command == expected
    assert command.as_payload() == payload
    with pytest.raises(FrozenInstanceError):
        command.name = "action.cycle_corner"  # type: ignore[misc]


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": True, "command": "action.cycle_corner"},
        {"schema_version": 1, "command": "action.reset_timer", "confirmed": False},
        {"schema_version": 1, "command": "action.cycle_corner", "extra": True},
        {"schema_version": 1, "command": "state.toggle_locked"},
        {"schema_version": 1, "command": "weapon.select", "weapon_id": ""},
        {
            "schema_version": 1,
            "command": "config.set_panel_visibility",
            "target": "arbitrary",
            "enabled": True,
        },
    ],
)
def test_command_schema_rejects_wrong_types_fields_and_non_allowlisted_actions(payload) -> None:
    with pytest.raises(ControlValidationError):
        validate_command_payload(payload)


def test_manual_semantic_command_construction_cannot_smuggle_irrelevant_fields() -> None:
    with pytest.raises(ControlValidationError):
        ValidatedWebCommand(name="action.cycle_corner", weapon_id="aim_9l")
    with pytest.raises(ControlValidationError):
        ValidatedWebCommand(name="state.set_locked")
    with pytest.raises(ControlValidationError):
        ValidatedWebCommand(name="weapon.set_ballistic_model", model="other")  # type: ignore[arg-type]


def test_control_store_validates_schema_and_requires_monotonic_revision() -> None:
    store = DashboardControlStore()
    initial = _projection(3)
    store.publish(initial)
    store.publish(initial)

    assert store.read() is initial
    with pytest.raises(ControlValidationError, match="regressed"):
        store.publish(_projection(2))
    changed_same_revision = ControlStateProjection(
        **{
            **initial.__dict__,
            "state": ControlTargetState(**{**initial.state.__dict__, "locked": True}),
        }
    )
    with pytest.raises(ControlValidationError, match="without a revision"):
        store.publish(changed_same_revision)


def test_control_store_rejects_schema_overflow_and_duplicate_capabilities() -> None:
    store = DashboardControlStore()
    initial = _projection()
    with pytest.raises(ControlValidationError):
        store.publish(ControlStateProjection(**{**initial.__dict__, "commands": COMMAND_NAMES * 2}))
    too_many_weapons = tuple(
        WeaponChoice(str(index), f"Weapon {index}", "test", True, False) for index in range(513)
    )
    with pytest.raises(ControlValidationError):
        store.publish(ControlStateProjection(**{**initial.__dict__, "weapons": too_many_weapons}))
    with pytest.raises(ControlValidationError, match="immutable tuples"):
        ControlStateProjection(**{**initial.__dict__, "commands": list(COMMAND_NAMES)})  # type: ignore[arg-type]


def test_control_state_payload_scopes_csrf_capabilities_and_recent_results() -> None:
    projection = _projection()
    recent = (
        {
            "command_id": "command-1",
            "command": "action.cycle_corner",
            "status": "succeeded",
            "reason": "ok",
            "submitted_revision": 1,
            "resulting_revision": 2,
        },
    )
    control = build_control_state_payload(
        projection,
        scope="control",
        transport="loopback",
        authorization_epoch=4,
        lan_control_enabled=False,
        csrf="c" * 43,
        recent_commands=recent,
    )
    view = build_control_state_payload(
        projection,
        scope="view",
        transport="lan",
        authorization_epoch=4,
        lan_control_enabled=False,
        csrf=None,
        recent_commands=recent,
    )

    validate_schema_payload(CONTROL_STATE_SCHEMA_NAME, control)
    validate_schema_payload(CONTROL_STATE_SCHEMA_NAME, view)
    assert control["csrf"] == "c" * 43
    assert control["recent_commands"] == list(recent)
    assert view["csrf"] is None
    assert view["capabilities"] == {"commands": [], "panel_targets": []}
    assert view["recent_commands"] == []


def test_command_response_schema_rejects_unknown_or_synchronous_results() -> None:
    validate_schema_payload(
        COMMAND_RESPONSE_SCHEMA_NAME,
        {
            "schema_version": 1,
            "command_id": "command-1",
            "status": "queued",
            "submitted_revision": 1,
        },
    )
    with pytest.raises(ControlValidationError):
        validate_schema_payload(
            COMMAND_RESPONSE_SCHEMA_NAME,
            {"schema_version": 1, "command_id": "command-1", "status": "succeeded"},
        )
