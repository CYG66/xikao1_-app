"""Failure diff gate for RELEASE-TEST-01 regression runs.

Compares the failing/errored testcases from freshly produced JUnit reports
against a reviewed baseline failure manifest, and classifies each item as:

* ``new``       - failing now, not listed in the baseline manifest.
* ``resolved``  - listed in the baseline, passing again now (improvement).
* ``unchanged`` - failing both now and in the baseline.

Collection errors are tracked separately by source file basename. The raw
collect-audit job exit code is propagated into this report via ``--collect-rc``
so a collection breakage cannot stay red in isolation only.

Gate semantics
---------------
* The raw pytest jobs always fail honestly on red tests; this script does not
  skip, rewrite, or reclassify a failing test as passing.
* The manifest is an explicit, reviewed allowlist of *known baseline reds*.
  A new failure (absent from the manifest) fails this gate by default.
* A collection-error file absent from the baseline manifest also fails this
  gate; files that disappeared since baseline are reported as resolved only.
* ``resolved`` items are reported as improvements; the manifest owner may
  later prune them from the baseline in a reviewed change.

Exit codes
----------
0  No new failures and no new collection errors (or ``--no-fail-on-new``).
1  At least one new failure / collection error was detected, or the collect
   audit evidence is missing while its exit code indicates breakage.

Usage
-----
    python scripts/ci/diff_failures.py \
        --junit reports/*.xml \
        --baseline baseline_failures.json \
        --collect-errors collect-errors.txt \
        --collect-rc collect-rc.txt \
        --output-json diff-report.json \
        --output-md diff-report.md
"""
from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path


def _case_key(classname: str, name: str) -> str:
    return f"{classname}::{name}"


def parse_junit(
    junit_paths: list[Path],
) -> tuple[set[str], int, int, list[str], list[str]]:
    """Return failing/errored case keys, counts, and missing/invalid reports.

    A missing, unparseable, or empty report is reported explicitly rather than
    treated as a clean zero-failure run.
    """
    failed: set[str] = set()
    skipped = 0
    total = 0
    missing: list[str] = []
    invalid: list[str] = []
    for junit in junit_paths:
        if not junit.is_file():
            missing.append(junit.name)
            continue
        try:
            tree = ET.parse(junit)
        except (ET.ParseError, OSError) as exc:
            invalid.append(f"{junit.name}: {exc}")
            continue
        cases = list(tree.iter("testcase"))
        if not cases:
            invalid.append(f"{junit.name}: no testcase in report")
            continue
        for case in cases:
            total += 1
            if case.find("skipped") is not None:
                skipped += 1
            if case.find("failure") is not None or case.find("error") is not None:
                failed.add(_case_key(case.get("classname", ""), case.get("name", "")))
    return failed, skipped, total, missing, invalid


def load_baseline(path: Path) -> dict[str, object]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.setdefault("known_failures", [])
    manifest.setdefault("known_collection_errors", [])
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Regression failure diff gate.")
    parser.add_argument("--junit", nargs="+", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--collect-errors", type=Path,
                        help="One collection-error file per line from the collect audit job.")
    parser.add_argument("--collect-rc", type=Path,
                        help="File holding the raw pytest collect-only exit code.")
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path)
    parser.add_argument("--no-fail-on-new", action="store_true",
                        help="Report new failures without failing the gate (diagnostic only).")
    args = parser.parse_args()

    current_failed, skipped, total, missing_reports, invalid_reports = parse_junit(args.junit)
    baseline = load_baseline(args.baseline)
    baseline_failed: set[str] = set(baseline["known_failures"])

    new_failures = sorted(current_failed - baseline_failed)
    resolved = sorted(baseline_failed - current_failed)
    unchanged = sorted(current_failed & baseline_failed)

    # Collection errors (source files), if a collect-error list was supplied.
    current_collect_errors: set[str] = set()
    new_collect_errors: list[str] = []
    resolved_collect_errors: list[str] = []
    baseline_collect_errors: set[str] = set(baseline["known_collection_errors"])
    collect_rc: int | None = None
    collect_evidence_missing = False

    if args.collect_rc and args.collect_rc.is_file():
        raw_rc = args.collect_rc.read_text(encoding="utf-8").strip()
        try:
            collect_rc = int(raw_rc)
        except ValueError:
            collect_rc = None

    if args.collect_errors:
        if args.collect_errors.is_file():
            current_collect_errors = {
                line.strip() for line in args.collect_errors.read_text(encoding="utf-8").splitlines()
                if line.strip()
            }
            new_collect_errors = sorted(current_collect_errors - baseline_collect_errors)
            resolved_collect_errors = sorted(baseline_collect_errors - current_collect_errors)
        else:
            # Evidence artifact absent: if the raw collect RC indicates
            # breakage, this cannot be treated as a clean collection.
            collect_evidence_missing = True

    collect_breakage_without_evidence = (
        collect_evidence_missing and collect_rc is not None and collect_rc != 0
    )

    report: dict[str, object] = {
        "totals": {"testcases": total, "skipped": skipped, "failing_now": len(current_failed)},
        "new_failures": new_failures,
        "resolved_failures": resolved,
        "unchanged_failures": unchanged,
        "collect_rc": collect_rc,
        "collect_errors_parsed": len(current_collect_errors),
        "collect_evidence_missing": collect_evidence_missing,
        "new_collection_errors": new_collect_errors,
        "resolved_collection_errors": resolved_collect_errors,
        "missing_reports": missing_reports,
        "invalid_reports": invalid_reports,
        "gate_passed": True,
    }

    # A missing or corrupt upstream report cannot be treated as a clean run:
    # we have no evidence the suite stayed green.
    has_new = bool(
        new_failures
        or new_collect_errors
        or collect_breakage_without_evidence
        or missing_reports
        or invalid_reports
    )
    report["gate_passed"] = not has_new or args.no_fail_on_new

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.output_md:
        lines = [
            "# Regression failure diff",
            "",
            f"- Testcases parsed: {total}",
            f"- Skipped: {skipped}",
            f"- Failing now: {len(current_failed)}",
            f"- Collect audit exit code: {collect_rc if collect_rc is not None else 'n/a'}",
            f"- New failures: {len(new_failures)}",
            f"- Resolved since baseline: {len(resolved)}",
            f"- Unchanged baseline reds: {len(unchanged)}",
            f"- New collection errors: {len(new_collect_errors)}",
            f"- Missing reports: {len(missing_reports)}",
            f"- Invalid reports: {len(invalid_reports)}",
            "",
        ]
        for title, items in (
            ("## New failures (must not enter the baseline silently)", new_failures),
            ("## Resolved", resolved),
            ("## Unchanged baseline reds", unchanged),
            ("## New collection errors", new_collect_errors),
            ("## Missing upstream reports", missing_reports),
            ("## Invalid upstream reports", invalid_reports),
        ):
            lines.append(title)
            if not items:
                lines.append("- (none)")
            else:
                lines.extend(f"- `{item}`" for item in items)
            lines.append("")
        args.output_md.write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps({k: report[k] for k in
                      ("new_failures", "resolved_failures", "unchanged_failures",
                       "collect_rc", "new_collection_errors", "missing_reports",
                       "invalid_reports", "gate_passed")},
                     ensure_ascii=False, indent=2))

    if has_new and not args.no_fail_on_new:
        if missing_reports:
            print("::error:: missing upstream JUnit reports: " + ", ".join(missing_reports))
        if invalid_reports:
            print("::error:: invalid upstream JUnit reports: " + "; ".join(invalid_reports))
        print("GATE FAILED: new failures/collection errors, missing/invalid reports, "
              "or unexplained collect breakage.")
        return 1
    print("GATE PASSED: no new failures or collection errors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
