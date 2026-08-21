from __future__ import annotations

import pytest

from bomana.release_closure import (
    SourceClosure,
    classify_source_path,
    public_release_includes,
)


@pytest.mark.parametrize(
    "path",
    [
        "bomana/core/weapon_solver.py",
        "bomana/data/offline_rigidbody_catalog.bin",
        "bomana/ui/bombing_runtime.py",
        "bomana/web/server.py",
        "bomana/assets/web/dashboard.js",
        "docs/specs/schemas/web-dashboard-command.schema.json",
    ],
)
def test_subscriber_source_never_enters_public_artifacts(path: str) -> None:
    assert classify_source_path(path) is SourceClosure.SUBSCRIBER
    assert not public_release_includes(path)


@pytest.mark.parametrize(
    "path",
    [
        "Bomana.pyw",
        "bomana/core/navigation.py",
        "bomana/editions.py",
        "bomana/ui/strike_prediction.py",
        "bomana/core/strike_encyclopedia.py",
        "bomana/data/strike_encyclopedia.json",
        "bomana/ui/strike_encyclopedia.py",
        "bomana/assets/branding/app.ico",
    ],
)
def test_public_source_remains_in_public_artifacts(path: str) -> None:
    assert classify_source_path(path) is SourceClosure.PUBLIC
    assert public_release_includes(path)


@pytest.mark.parametrize("path", ["", "../secret", "/absolute/path"])
def test_release_closure_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(ValueError, match="invalid release source path"):
        classify_source_path(path)
