"""D-owned C-line service Mock dependency-pending probe (read-only).

Re-runs the C baseline service-level Mock modules against the C worktree
backend and separates genuine product failures from ``failed_dep_pending``
cases that block on A1.1 / B1 not being merged into a combined backend.

Classification:
- failure message carrying ``failed_dep_pending`` -> ``not_run`` /
  ``dependency_pending`` (external dependency pending; not a C-side logic
  failure, not a relaxed assertion).
- any other failure -> the D1 taxonomy logic/error-mapping classes from the
  shared runner classifier.

Hard guards: provider forced local; model keys stripped; no live model call,
no persistence; target tree is imported/run read-only.

Usage:
    python evaluations/v1/probes/d1_c_mock_probe.py \
        --backend "C:\\Users\\29924\\Codes\\worktrees\\C\\backend" \
        --out evaluations/v1/probes/d1_c_mock_results.json
"""
from __future__ import annotations

import argparse
import hashlib
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
]

PENDING_MARKER = "failed_dep_pending"


def _classify_case(tag: str, message: str, text: str) -> dict[str, str]:
    if PENDING_MARKER in f"{message}\n{text}":
        return {"failure_class": "not_run", "sub_class": "dependency_pending"}
    return runner.classify_testcase(tag, message, text)


def main() -> int:
    parser = argparse.ArgumentParser(description="D1.1 C mock dependency-pending probe")
    parser.add_argument("--backend", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--label", default="C1-3796180")
    parser.add_argument("--target-ref", default="3796180")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="d1_c_mock_"))
    suites: list[dict[str, Any]] = []
    for idx, module in enumerate(MODULES, start=1):
        junit = tmp / f"c_mock_{idx}.xml"
        result = runner.run_pytest(module, junit, args.backend)
        for case in result.get("cases", []):
            classification = _classify_case(
                "skipped" if case["outcome"] == "skipped"
                else "error" if case["outcome"] == "error" else "failure"
                if case["outcome"] == "failure" else "passed",
                case.get("message", ""), case.get("message", ""),
            )
            case["classification"] = classification
        suites.append({"module": module, **result})

    pending = [
        case["node"]
        for suite in suites for case in suite.get("cases", [])
        if case["classification"]["failure_class"] == "not_run"
    ]

    payload: dict[str, Any] = {
        "schema": "cad.d1.c-mock.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "label": args.label,
        "target_backend": str(args.backend),
        "git": {
            "head_sha": runner._git(["rev-parse", "HEAD"], args.backend),
            "branch": runner._git(["rev-parse", "--abbrev-ref", "HEAD"], args.backend),
            "status_short": runner._git(["status", "--short"], args.backend),
            "claimed_target_ref": args.target_ref,
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
        "combination": {
            "combined_worktree_provided": False,
            "combined_sha": None,
            "note": "C 侧一次性组合 worktree（A1.1 + C 服务基线）路径与组合 SHA 未提供；"
                    "本快照仅为 C 基线后端上的依赖挂起核验，不等于组合后端通过。",
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
                      "counts": payload["counts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
