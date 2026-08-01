"""Source-closure policy for the public Bomana repository."""

from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final


class SourceClosure(StrEnum):
    """The repository closure that owns a source path."""

    PUBLIC = "public"
    SUBSCRIBER = "subscriber"


SUBSCRIBER_SOURCE_FILES: Final = frozenset(
    {
        "bomana/core/atmosphere.py",
        "bomana/core/ballistics.py",
        "bomana/core/ccrp_scheduler.py",
        "bomana/core/offline_ballistics_model.py",
        "bomana/core/offline_rigidbody_catalog.py",
        "bomana/core/offline_rigidbody_properties.py",
        "bomana/core/offline_rigidbody_solver.py",
        "bomana/core/release_observation.py",
        "bomana/core/terrain_elevation.py",
        "bomana/core/visible_trajectory_reference.py",
        "bomana/core/weapon_catalog.py",
        "bomana/core/weapon_envelope.py",
        "bomana/core/weapon_scheduler.py",
        "bomana/core/weapon_solver.py",
        "bomana/ui/bombing_bar.py",
        "bomana/ui/bombing_runtime.py",
        "bomana/data/offline_rigidbody_catalog.bin",
        "bomana/data/visible_trajectory_references.json",
        "bomana/data/weapon_fire_control.json",
        "docs/specs/schemas/weapon-fire-control.schema.json",
        "docs/specs/schemas/web-dashboard-command.schema.json",
        "docs/specs/schemas/web-dashboard-command-response.schema.json",
        "docs/specs/schemas/web-dashboard-control-state.schema.json",
    }
)

SUBSCRIBER_SOURCE_PREFIXES: Final = (
    "bomana/web/",
    "bomana/assets/web/",
    "bomana/data/terrain-",
)


def normalize_source_path(value: str | PurePosixPath) -> str:
    """Return a repository-relative POSIX path or fail closed."""

    text = str(value).replace("\\", "/").strip()
    path = PurePosixPath(text)
    if not text or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"invalid release source path: {value!r}")
    return path.as_posix()


def classify_source_path(value: str | PurePosixPath) -> SourceClosure:
    """Classify one source path without consulting build-time feature flags."""

    path = normalize_source_path(value)
    if path in SUBSCRIBER_SOURCE_FILES or any(
        path == prefix.rstrip("/") or path.startswith(prefix)
        for prefix in SUBSCRIBER_SOURCE_PREFIXES
    ):
        return SourceClosure.SUBSCRIBER
    return SourceClosure.PUBLIC


def public_release_includes(value: str | PurePosixPath) -> bool:
    """Return whether a path belongs in a public App or Launcher artifact."""

    return classify_source_path(value) is SourceClosure.PUBLIC


__all__ = [
    "SUBSCRIBER_SOURCE_FILES",
    "SUBSCRIBER_SOURCE_PREFIXES",
    "SourceClosure",
    "classify_source_path",
    "normalize_source_path",
    "public_release_includes",
]
