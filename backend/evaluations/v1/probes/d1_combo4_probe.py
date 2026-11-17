"""D-owned A1.1 + B1.2 + C1.2 combo independent verification probe (read-only).

One-shot non-final combo worktree merging A1.1 ``ea8323a``, B1.2 ``d7e00bd``
and C1.2 ``49d48de``. Re-runs the five D0 specialized suites, the 37 executor
cases, the 74 interpreter cases, the A1.1 repair suite, the B1/B11/B12
topology suites and the C1/C11/C12 service-loop Mock modules.

Outcome buckets stay separate (never merged into one pass rate):
- ``detection``: B1/B11/B12 topology contact / unresolved detection outcomes.
- ``repair_mock``: A1.1 repair and C1/C11/C12 service-loop Mock outcomes.
- ``regression``: pre-existing rule-path suites.
- ``real_generation``: always ``not_run``; no live model call is made.

The combo branch is NOT a final integration branch: it must not be merged,
pushed or treated as the formal integration decision.
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

SUITES: list[dict[str, str]] = [
    {"group": "S1-requirement-contract", "bucket": "regression",
     "module": "tests/test_cad_requirement_contract.py"},
    {"group": "S2-plan-component-repair", "bucket": "repair_mock",
     "module": "tests/test_cad_plan_component_repair.py"},
    {"group": "S3-final-source-contract", "bucket": "regression",
     "module": "tests/test_cad_final_source_contract.py"},
    {"group": "S4-construction-interpreter", "bucket": "regression",
     "module": "tests/test_cad_construction_interpreter.py"},
    {"group": "S5-candidate-visibility-gate", "bucket": "regression",
     "module": "tests/test_candidate_visibility_gate.py"},
    {"group": "executor-construction", "bucket": "regression",
     "module": "tests/test_cad_construction.py"},
    {"group": "B1-topology-detection", "bucket": "detection",
     "module": "tests/test_cad_topology_safety_b1.py"},
    {"group": "B11-topology-detection", "bucket": "detection",
     "module": "tests/test_cad_topology_safety_b11.py"},
    {"group": "B12-arcspline-detection", "bucket": "detection",
     "module": "tests/test_cad_topology_safety_b12.py"},
    {"group": "C1-service-mock", "bucket": "repair_mock",
     "module": "tests/test_c1_integration_mock.py"},
    {"group": "C11-two-round-service-mock", "bucket": "repair_mock",
     "module": "tests/test_c11_service_two_round_mock.py"},
    {"group": "C12-production-loop-mock", "bucket": "repair_mock",
     "module": "tests/test_c12_production_loop_mock.py"},
]

PENDING_MARKER = "failed_dep_pending"


def classify_case(case: dict[str, Any]) -> dict[str, str]:
    if PENDING_MARKER in f"{case.get('message', '')}":
        return {"failure_class": "not_run", "sub_class": "dependency_pending"}
    return runner.classify_testcase(case["outcome"], case.get("message", ""),
                                    case.get("message", ""))


def main() -> int:
    parser = argparse.ArgumentParser(description="D1.3 A1.1+B1.2+C1.2 combo probe")
    parser.add_argument("--backend", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--label", default="A11+B12+C12-combo")
    parser.add_argument("--base-commit",
                        default="ea8323a230f1cd53cf80f4fd4398328e836962b2")
    parser.add_argument("--b-commit",
                        default="d7e00bdb3bddd5d3c60daedc033e86c7c418c76d")
    parser.add_argument("--c-commit",
                        default="49d48de0f3d3790d47bf57599ac15bd202eca938")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="d1_combo4_"))
    suites: list[dict[str, Any]] = []
    for idx, spec in enumerate(SUITES, start=1):
        junit = tmp / f"combo4_{idx}.xml"
        result = runner.run_pytest(spec["module"], junit, args.backend)
        for case in result.get("cases", []):
            case["classification"] = classify_case(case)
        suites.append({"group": spec["group"], "bucket": spec["bucket"],
                       **result})

    collect = runner.run_collect_only(args.backend)

    def bucket_totals(bucket: str) -> dict[str, int]:
        blocks = [s for s in suites if s["bucket"] == bucket]
        return {
            "tests": sum(s["counts"]["tests"] for s in blocks),
            "passed": sum(s["counts"]["passed"] for s in blocks),
            "failed": sum(s["counts"]["failed"] for s in blocks),
            "errors": sum(s["counts"]["errors"] for s in blocks),
            "skipped": sum(s["counts"]["skipped"] for s in blocks),
            "not_run": sum(s["counts"]["not_run"] for s in blocks),
        }

    pending = [
        case["node"]
        for suite in suites for case in suite.get("cases", [])
        if case["classification"]["failure_class"] == "not_run"
    ]

    payload: dict[str, Any] = {
        "schema": "cad.d1.combo4.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "label": args.label,
        "target_backend": str(args.backend),
        "branch_note": "一次性非最终集成分支；不合并、不推送、不作正式集成结论依据。",
        "git": {
            "head_sha": runner._git(["rev-parse", "HEAD"], args.backend),
            "branch": runner._git(["rev-parse", "--abbrev-ref", "HEAD"], args.backend),
            "status_short": runner._git(["status", "--short"], args.backend),
            "merge_b_commit": runner._git(["rev-parse", "84640e7"], args.backend),
            "merge_c_commit": runner._git(["rev-parse", "f89bf41"], args.backend),
            "base_a_commit": args.base_commit,
            "b_tip_commit": args.b_commit,
            "c_tip_commit": args.c_commit,
        },
        "environment": {
            "python_executable": sys.executable,
            "versions": runner.package_versions(),
            "guard": runner.env_guard(),
        },
        "guards": {
            "live_model_calls": 0,
            "project_or_candidate_writes": "isolated_tmp_store_in_c12_only",
            "production_code_modified": False,
            "real_generation_outcome": "not_run",
        },
        "suites": suites,
        "collect_only": collect,
        "pending_dependency_cases": pending,
        "buckets": {
            "detection": bucket_totals("detection"),
            "repair_mock": bucket_totals("repair_mock"),
            "regression": bucket_totals("regression"),
            "real_generation": {"tests": 0, "passed": 0, "outcome": "not_run",
                                 "reason": "本轮未授权真实模型；服务 Mock 仅替换模型文本出口。"},
        },
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
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(json.dumps({"out": str(args.out), "sha256": digest,
                      "counts": payload["counts"], "buckets": payload["buckets"],
                      "head": payload["git"]["head_sha"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
