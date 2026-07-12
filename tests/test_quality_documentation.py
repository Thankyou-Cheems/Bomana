from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

TOP_LEVEL_MARKDOWN = {
    "ARCHITECTURE.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "PITFALLS.md",
    "PRIVACY.md",
    "QUICKSTART.md",
}
MARKDOWN_FILES = (
    ROOT / "README.md",
    ROOT / "README.en.md",
    ROOT / "AGENTS.md",
    ROOT / "tests" / "README.md",
    *sorted(DOCS.rglob("*.md")),
)
LINK_RE = re.compile(r"!?\[[^\]]+\]\(([^)]+)\)")


def test_top_level_docs_are_current_entrypoints() -> None:
    actual = {path.name for path in DOCS.glob("*.md")}

    assert actual == TOP_LEVEL_MARKDOWN


def test_repository_local_markdown_links_resolve() -> None:
    problems: list[str] = []

    for source in MARKDOWN_FILES:
        for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            for raw_target in LINK_RE.findall(line):
                target = raw_target.strip().split()[0].strip("<>")
                if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                    continue
                path_text = target.split("#", 1)[0]
                resolved = (source.parent / path_text).resolve()
                try:
                    resolved.relative_to(ROOT)
                except ValueError:
                    problems.append(
                        f"{source.relative_to(ROOT)}:{line_number}: {target} escapes repo"
                    )
                    continue
                if not resolved.exists():
                    problems.append(f"{source.relative_to(ROOT)}:{line_number}: missing {target}")

    assert problems == []


def test_readme_app_release_badge_tracks_latest_full_release() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "img.shields.io/github/v/release/Thankyou-Cheems/Bomana" in readme
    assert "filter=v*.*.*-app" not in readme
