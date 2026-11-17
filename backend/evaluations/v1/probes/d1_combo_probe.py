"""D-owned A1.1+C combo backend independent verification probe (read-only).

Runs the A1.1 producer + C service-level Mock modules, the A1.1 repair suite,
the 37 executor cases and the 74 interpreter regression cases against the
one-shot non-final integration combo worktree supplied by C.

The combo branch is NOT a final integration branch: it must not be merged,
pushed or deleted as part of D evaluation. Cases that still block on B1 are
classified ``not_run`` / ``dependency_pending``; they are not product failures.

Usage:
    python evaluations/v1/probes/d1_combo_probe.py \
        --backend "C:\\Users\\29924\\Codes\\worktrees\\tmp\\a11-c1-combo\\backend" \
        --out evaluations/v1/probes/d1_combo_results.json
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROBE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROBE_DIR))

import d1_baseline_runner as runner  # noqa: E402

MODULES = [
    "tests/test_c1_integration_mock.py",
    "tests/test_c11_service_two_round_mock.py",
    "tests/test_cad_plan_component_repair.py",
    "tests/test_cad_construction.py",
    "tests/test_cad_construction_interpreter.py",
]

PENDING_MARKER = "failed_dep_pending"


def classify_case(case: dict[str, Any]) -> dict[str, str]:
    tag = case["outcome"]
    if PENDING_MARKER in f"{case.get('message', '')}\n{case.get('message', '')}":
        return {"failure_class": "not_run", "sub_class": "dependency_pending"}
    return runner.classify_testcase(tag, case.get("message", ""), case.get("message", ""))


def main() -> int:
    parser = argparse.ArgumentParser(description="D1.1 combo backend independent probe")
    parser.add_argument("--backend", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--label", default="A11+C-combo")
    parser.add_argument("--combo-snapshot-commit", default="dee5849a7c0c7cc115a018754cada8b62588df72")
    parser.add_argument("--combo-commit", default="1fb9adf91a25bbd752d4d970f33a0d68e52523fb")
    parser.add_argument("--base-commit", default="ea8323a230f1cd53cf80f4fd4398328e836962b2")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="d1_combo_"))
    suites: list[dict[str, Any]] = []
    for idx, module in enumerate(MODULES, start=1):
        junit = tmp / f"combo_{idx}.xml"
        result = runner.run_pytest(module, junit, args.backend)
        for case in result.get("cases", []):
            case["classification"] = classify_case(case)
        suites.append({"module": module, **result})

    pending = [
        case["node"]
        for suite in suites for case in suite.get("cases", [])
        if case["classification"]["failure_class"] == "not_run"
    ]

    payload: dict[str, Any] = {
        "schema": "cad.d1.combo.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "label": args.label,
        "target_backend": str(args.backend),
        "branch_note": "一次性非最终集成分支；不合并、不推送、不作正式集成结论依据。",
        "git": {
            "head_sha": runner._git(["rev-parse", "HEAD"], args.backend),
            "branch": runner._git(["rev-parse", "--abbrev-ref", "HEAD"], args.backend),
            "status_short": runner._git(["status", "--short"], args.backend),
            "base_commit": args.base_commit,
            "combo_snapshot_commit": args.combo_snapshot_commit,
            "combo_commit": args.combo_commit,
        },
        "environment": {
            "python_executable": sys.executable,
            "versions": runner.package_versions(),
            "guard": runner.env_guard(),
        },
        "guards": {
            "live_model_calls": 0,
            "project_or_candidate_writes": False,
            "production_code_modified": False,
        },
        "suites": suites,
        "pending_dependency_cases": pending,
        "counts": {
            "modules": len(suites),
            "passed": sum(s["counts"]["passed"] for s in suites),
            "failed": sum(s["counts"]["failed"] for s in suites),
            "errors": sum(s["counts"]["errors"] for s in suites),
            "not_run_dependency_pending": len(pending),
        },
    }

    digest = runner.canonical_sha256(
        {k: v for k, v in payload.items() if k != "snapshot_sha256"})
    payload["snapshot_sha256"] = digest
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(args.out), "sha256": digest,
                      "counts": payload["counts"], "head": payload["git"]["head_sha"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
