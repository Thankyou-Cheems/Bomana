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


def test_readme_version_badges_use_cdn_not_github_latest() -> None:
    """GitHub 'latest' is often a launcher-only tag; player versions live on CDN."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_en = (ROOT / "README.en.md").read_text(encoding="utf-8")

    for text in (readme, readme_en):
        assert "bomanaupdate.ruikang.wang%2Fapi%2Fv1%2Fversion" in text
        assert "bomanaupdate.ruikang.wang%2Fapi%2Fv1%2Flauncher" in text
        assert "img.shields.io/github/v/release/Thankyou-Cheems/Bomana" not in text
        assert 'align="center"' in text
        assert "bomana/assets/branding/app.png" in text
