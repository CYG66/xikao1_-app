"""Manual field-test inventory gate for RELEASE-TEST-01.

What this gate does
-------------------
* Verifies that the ``manual_field`` pytest marker is registered in the pytest
  configuration (an unknown marker would be a configuration failure, not a
  silent warning).
* Collects tests tagged ``manual_field`` **without executing them**
  (``--collect-only``) and writes the inventory to ``collected-manual.json``.
* Optionally cross-checks an offline regression JUnit report: no collected
  manual test may have been executed by the offline jobs.

What this gate must NEVER do
----------------------------
* Execute a ``manual_field`` test (real rover movement, inkjet/pen output,
  live ROS bridge, live model session).  The manual suite belongs to on-site
  validation and is out of scope for CI.
* Rewrite, skip, or deselect a collected manual item to make the inventory
  look empty.

Exit codes
----------
0  Marker registered; collection inventory written; (if checked) no manual
   test appears in the offline executed report.
1  Marker unknown, collection failed, or a manual test leaked into an offline
   executed report.

Usage
-----
    python scripts/ci/check_manual_collection.py \
        --root BACKEND_ROOT \
        --tests-dir tests \
        --junit-report offline-junit.xml \
        --output collected-manual.json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

MARKER_DEFAULT = "manual_field"
# A collected node in pytest -q collect-only output:
#   tests/test_foo.py::TestClass::test_case[param]
_NODE_RE = re.compile(r"^(?P<file>tests/[^\s:]+::[^\s]+)$")


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, check=False,
    )


def marker_is_registered(backend_root: Path, marker: str) -> tuple[bool, str]:
    proc = _run([sys.executable, "-m", "pytest", "--markers"], backend_root)
    output = proc.stdout + proc.stderr
    pattern = re.compile(rf"@(?:pytest\.mark\.)?{re.escape(marker)}\b")
    registered = any(pattern.match(line.lstrip()) for line in output.splitlines())
    return registered, output


def collect_manual(backend_root: Path, tests_dir: str, marker: str) -> tuple[int, list[str], str]:
    proc = _run(
        [
            sys.executable, "-m", "pytest",
            tests_dir,
            "--collect-only", "-q",
            "-m", marker,
            "-p", "no:cacheprovider",
        ],
        backend_root,
    )
    inventory: list[str] = []
    for line in (proc.stdout + "\n" + proc.stderr).splitlines():
        line = line.strip()
        match = _NODE_RE.match(line)
        if match:
            inventory.append(match.group("file"))
    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique = [node for node in inventory if not (node in seen or seen.add(node))]
    return proc.returncode, unique, proc.stdout + proc.stderr


def junit_report_node_ids(junit_path: Path) -> set[str]:
    """Convert JUnit testcases to pytest-style node ids for the leak check."""
    import xml.etree.ElementTree as ET

    ids: set[str] = set()
    if not junit_path.is_file():
        raise FileNotFoundError(f"JUnit report not found: {junit_path}")
    tree = ET.parse(junit_path)
    for case in tree.iter("testcase"):
        classname = case.get("classname", "")
        name = case.get("name", "")
        if not classname:
            continue
        parts = classname.split(".")
        if len(parts) >= 3:
            # Class-based test: tests.<module>.<ClassName>
            module_parts, klass = parts[:-1], parts[-1]
            module_path = "/".join(module_parts) + ".py"
            node_id = f"{module_path}::{klass}::{name}"
        elif len(parts) == 2 and parts[0] == "tests":
            # Module-level function test: tests.<module>
            node_id = f"tests/{parts[1]}.py::{name}"
        else:
            node_id = f"{classname}::{name}"
        ids.add(node_id)
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(description="Manual field-test inventory gate.")
    default_root = Path(__file__).resolve().parents[2]
    parser.add_argument("--root", type=Path, default=default_root)
    parser.add_argument("--tests-dir", default="tests")
    parser.add_argument("--marker", default=MARKER_DEFAULT)
    parser.add_argument("--junit-report", type=Path,
                        help="Offline regression JUnit report to cross-check.")
    parser.add_argument("--output", type=Path, default=Path("collected-manual.json"))
    args = parser.parse_args()

    backend_root = args.root.resolve()

    registered, markers_output = marker_is_registered(backend_root, args.marker)
    if not registered:
        print(f"[FAIL] marker '{args.marker}' is not registered in pytest configuration.")
        print("Registered markers:")
        print(markers_output)
        return 1
    print(f"[OK] marker '{args.marker}' is registered.")

    collect_rc, nodes, collect_output = collect_manual(backend_root, args.tests_dir, args.marker)
    # pytest returns 5 when no tests are collected; an empty manual inventory
    # is a valid state before any on-device test is tagged. Real collection
    # breakage uses exit code 2 and must still fail the gate.
    if collect_rc not in (0, 5):
        print("[FAIL] manual collection exited non-zero:")
        print(collect_output)
        return 1

    report: dict[str, object] = {
        "marker": args.marker,
        "executed": False,
        "collected_count": len(nodes),
        "collected": nodes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] collected {len(nodes)} manual test(s) (not executed); "
          f"inventory written to {args.output}")

    if args.junit_report:
        executed = junit_report_node_ids(args.junit_report)
        leaked = sorted(set(nodes) & executed)
        if leaked:
            print("[FAIL] manual test(s) were executed by an offline job:")
            for node in leaked:
                print(f"  - {node}")
            return 1
        print("[OK] no collected manual test appears in the offline executed report.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
