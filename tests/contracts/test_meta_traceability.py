# enforces: docs/specs/testing-quality-gates.md QG-05
#
# Copied from the spec-anchored-development skill. It checks classified clause
# coverage and both directions of the spec/test map.

import re
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]  # tests/contracts/ -> repo root
SPECS = REPO / "docs" / "specs"
CONTRACTS = REPO / "tests" / "contracts"

COVERAGE_CLASSES = ("static", "behavioral", "manual")
COVERAGE_RE = re.compile(r"`(tests/[\w./-]+\.py)`")
ENFORCES_RE = re.compile(
    r"^#\s*enforces:\s*(docs/specs/[\w./-]+\.md)\s+(.+?)\s*$",
    re.MULTILINE,
)
CLAUSE_TOKEN_RE = re.compile(
    r"(?<![A-Z0-9-])"
    r"(?P<prefix>[A-Z][A-Z0-9-]*-)"
    r"(?P<start>\d{2})"
    r"(?:\.\."
    r"(?:(?P<end_prefix>[A-Z][A-Z0-9-]*-))?"
    r"(?P<end>\d{2}))?"
)
COVERAGE_ITEM_RE = re.compile(
    r"^-\s+\[(static|behavioral|manual)\]\s+"
    r"(.*?)(?=^-\s+\[(?:static|behavioral|manual)\]\s+|\Z)",
    re.MULTILINE | re.DOTALL,
)


def _extract_section(text: str, title: str) -> str:
    """Return the body of the '## <title>' section, or '' if absent."""
    match = re.search(
        rf"^#{{2,}}\s+{re.escape(title)}\s*$(.*?)(?=^#{{2,}}\s|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return match.group(1) if match else ""


def _clauses_in(text: str) -> set[str]:
    clauses: set[str] = set()
    for match in CLAUSE_TOKEN_RE.finditer(text):
        prefix = match.group("prefix")
        start_text = match.group("start")
        end_text = match.group("end")
        if end_text is None:
            clauses.add(f"{prefix}{start_text}")
            continue

        end_prefix = match.group("end_prefix") or prefix
        if end_prefix != prefix:
            raise AssertionError(f"cross-prefix clause range is invalid: {match.group(0)}")
        start = int(start_text)
        end = int(end_text)
        if end < start:
            raise AssertionError(f"descending clause range is invalid: {match.group(0)}")
        width = len(start_text)
        clauses.update(f"{prefix}{number:0{width}d}" for number in range(start, end + 1))
    return clauses


def _spec_contract_map() -> tuple[
    dict[str, set[str]],
    dict[tuple[str, str], set[str]],
    list[str],
]:
    spec_clauses: dict[str, set[str]] = {}
    mapped_contract_clauses: dict[tuple[str, str], set[str]] = defaultdict(set)
    problems: list[str] = []

    for spec in sorted(SPECS.glob("*.md")):
        spec_rel = spec.relative_to(REPO).as_posix()
        text = spec.read_text(encoding="utf-8")
        normative = _extract_section(text, "Normative Clauses")
        coverage = _extract_section(text, "Contract Coverage")
        clauses = _clauses_in(normative)
        spec_clauses[spec_rel] = clauses

        if not clauses:
            problems.append(f"{spec.name}: no normative clauses found")
        if not coverage:
            problems.append(f"{spec.name}: missing Contract Coverage section")
            continue

        for line in coverage.splitlines():
            if line.startswith("- ") and not line.startswith(
                tuple(f"- [{kind}]" for kind in COVERAGE_CLASSES)
            ):
                problems.append(f"{spec.name}: unclassified coverage bullet: {line}")

        covered: set[str] = set()
        items = list(COVERAGE_ITEM_RE.finditer(coverage))
        if not items:
            problems.append(f"{spec.name}: no classified coverage bullets found")
            continue

        for item in items:
            kind, body = item.groups()
            item_clauses = _clauses_in(body)
            test_paths = COVERAGE_RE.findall(body)
            if not item_clauses:
                problems.append(f"{spec.name}: [{kind}] bullet names no clause IDs")
            if kind != "manual" and not test_paths:
                problems.append(f"{spec.name}: [{kind}] bullet must reference a tests/*.py file")
            covered.update(item_clauses)

            for path in test_paths:
                if not (REPO / path).exists():
                    problems.append(f"{spec.name}: missing referenced test {path}")
                if path.startswith("tests/contracts/"):
                    mapped_contract_clauses[(spec_rel, path)].update(item_clauses)

        missing = clauses - covered
        unknown = covered - clauses
        if missing:
            problems.append(f"{spec.name}: uncovered clauses: {sorted(missing)}")
        if unknown:
            problems.append(f"{spec.name}: coverage names unknown clauses: {sorted(unknown)}")

    return spec_clauses, dict(mapped_contract_clauses), problems


def test_spec_clauses_have_classified_coverage() -> None:
    """Every clause has static, behavioral, or manual coverage with valid paths."""
    _spec_clauses, _mapped_contract_clauses, problems = _spec_contract_map()
    assert not problems, "\n".join(problems)


def test_contract_headers_match_spec_coverage() -> None:
    """Every contract header cites real clauses and agrees with the owning spec."""
    spec_clauses, mapped_contract_clauses, problems = _spec_contract_map()

    for test_file in sorted(CONTRACTS.glob("test_*.py")):
        test_rel = test_file.relative_to(REPO).as_posix()
        text = test_file.read_text(encoding="utf-8")[:2000]
        first_line = text.partition("\n")[0]
        if not first_line.startswith("# enforces: docs/specs/"):
            problems.append(f"{test_file.name}: first line must be an exact spec-clause header")
        matches = list(ENFORCES_RE.finditer(text))
        if not matches:
            problems.append(
                f"{test_file.name}: missing '# enforces: docs/specs/<spec>.md CLAUSE-01' header"
            )
            continue

        claimed_by_spec: dict[str, set[str]] = defaultdict(set)
        for match in matches:
            spec_rel, expression = match.groups()
            claimed = _clauses_in(expression)
            if spec_rel not in spec_clauses:
                problems.append(f"{test_file.name}: enforces nonexistent spec {spec_rel}")
                continue
            if not claimed:
                problems.append(f"{test_file.name}: header for {spec_rel} names no clauses")
                continue
            unknown = claimed - spec_clauses[spec_rel]
            if unknown:
                problems.append(
                    f"{test_file.name}: header names unknown clauses in {spec_rel}: "
                    f"{sorted(unknown)}"
                )
            claimed_by_spec[spec_rel].update(claimed)

        for spec_rel, claimed in claimed_by_spec.items():
            mapped = mapped_contract_clauses.get((spec_rel, test_rel), set())
            if claimed != mapped:
                problems.append(
                    f"{test_file.name}: header/spec coverage mismatch for {spec_rel}: "
                    f"header={sorted(claimed)}, coverage={sorted(mapped)}"
                )

    assert not problems, "\n".join(problems)
