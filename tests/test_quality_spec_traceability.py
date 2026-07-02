import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _contract_coverage_section(source: str) -> str:
    marker = "## Contract Coverage"
    if marker not in source:
        return ""
    section = source.split(marker, 1)[1]
    next_heading = re.search(r"\n## ", section)
    if next_heading:
        return section[: next_heading.start()]
    return section


def test_spec_contract_coverage_references_existing_files() -> None:
    missing: list[str] = []
    specs = sorted((ROOT / "docs/specs").glob("*.md"))
    assert specs

    for spec in specs:
        section = _contract_coverage_section(spec.read_text(encoding="utf-8"))
        assert section.strip(), f"{spec.relative_to(ROOT)} missing Contract Coverage"
        for relative in sorted(set(re.findall(r"`((?:tests|tools)/[^`]+)`", section))):
            if not (ROOT / relative).exists():
                missing.append(f"{spec.relative_to(ROOT)} -> {relative}")

    assert missing == []
