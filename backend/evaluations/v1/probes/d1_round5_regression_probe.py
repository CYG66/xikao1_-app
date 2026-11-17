"""Round-5 D-line regression probe: combo HEAD vs C-parent attribution.

Zero model calls, no network. Re-runs the 12 baseline suites (184 cases at
f89bf41), C's new M2/M3 loop-mock module, the recovery module and the
route-boundary adjacent suite against the round5 combo tree. The same command
is then run against C's parent commit ``8e3efad`` for the C1/C11/C12 mocks and
the boundary suite, so each pre-existing failure can be attributed as
``preexisting`` or ``introduced_round5``.

Usage:
    python d1_round5_regression_probe.py --combo-backend <combo/backend> \
        --parent-backend <c-parent/backend> --d-probes <D probes> --out <json>
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys
import tempfile

BASELINE_SUITES = [
    ("S1-requirement-contract", "regression", "tests/test_cad_requirement_contract.py"),
    ("S2-plan-component-repair", "repair_mock", "tests/test_cad_plan_component_repair.py"),
    ("S3-final-source-contract", "regression", "tests/test_cad_final_source_contract.py"),
    ("S4-construction-interpreter", "regression", "tests/test_cad_construction_interpreter.py"),
    ("S5-candidate-visibility-gate", "regression", "tests/test_candidate_visibility_gate.py"),
    ("executor-construction", "regression", "tests/test_cad_construction.py"),
    ("B1-topology-detection", "detection", "tests/test_cad_topology_safety_b1.py"),
    ("B11-topology-detection", "detection", "tests/test_cad_topology_safety_b11.py"),
    ("B12-arcspline-detection", "detection", "tests/test_cad_topology_safety_b12.py"),
    ("C1-service-mock", "repair_mock", "tests/test_c1_integration_mock.py"),
    ("C11-two-round-service-mock", "repair_mock", "tests/test_c11_service_two_round_mock.py"),
    ("C12-production-loop-mock", "repair_mock", "tests/test_c12_production_loop_mock.py"),
]

ROUND5_SUITES = [
    ("C13-m2m3-loop-mock", "repair_mock", "tests/test_c13_m2m3_loop_mock.py"),
    ("recovery-generation", "regression", "tests/test_cad_generation_recovery.py"),
    ("agent-service-boundaries", "regression", "tests/test_agent_service_boundaries.py"),
]

# Suites re-run on C parent 8e3efad for failure attribution.
PARENT_SUITES = [
    ("C1-service-mock", "repair_mock", "tests/test_c1_integration_mock.py"),
    ("C11-two-round-service-mock", "repair_mock", "tests/test_c11_service_two_round_mock.py"),
    ("C12-production-loop-mock", "repair_mock", "tests/test_c12_production_loop_mock.py"),
    ("agent-service-boundaries", "regression", "tests/test_agent_service_boundaries.py"),
]


def run_suites(backend: pathlib.Path, suites, tmp: pathlib.Path, runner) -> list[dict]:
    out = []
    for idx, (group, bucket, module) in enumerate(suites, start=1):
        junit = tmp / f"r5_{backend.name}_{idx}.xml"
        result = runner.run_pytest(module, junit, backend)
        result["group"] = group
        result["bucket"] = bucket
        out.append(result)
    return out


def summarize(suites: list[dict]) -> dict[str, int]:
    return {
        "tests": sum(s["counts"]["tests"] for s in suites),
        "passed": sum(s["counts"]["passed"] for s in suites),
        "failed": sum(s["counts"]["failed"] for s in suites),
        "errors": sum(s["counts"]["errors"] for s in suites),
        "skipped": sum(s["counts"]["skipped"] for s in suites),
        "not_run": sum(s["counts"]["not_run"] for s in suites),
    }


def failed_cases(suites: list[dict]) -> list[dict]:
    rows = []
    for s in suites:
        for c in s.get("cases", []):
            if c["outcome"] != "passed":
                rows.append({"group": s["group"], "node": c["node"],
                             "outcome": c["outcome"],
                             "failure_class": c["failure_class"],
                             "sub_class": c["sub_class"],
                             "message": c["message"]})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--combo-backend", required=True, type=pathlib.Path)
    ap.add_argument("--parent-backend", required=True, type=pathlib.Path)
    ap.add_argument("--d-probes", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    args = ap.parse_args()

    sys.path.insert(0, str(args.d_probes))
    import d1_baseline_runner as runner  # noqa: PLC0415

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="xline-d1-r5-reg-"))

    combo = run_suites(args.combo_backend, BASELINE_SUITES + ROUND5_SUITES, tmp, runner)
    parent = run_suites(args.parent_backend, PARENT_SUITES, tmp, runner)

    combo_baseline = combo[: len(BASELINE_SUITES)]
    combo_round5 = combo[len(BASELINE_SUITES):]

    # Attribution: node present and non-passing in parent -> preexisting;
    # non-passing only in combo -> introduced_round5.
    parent_nodes = {c["node"] for s in parent for c in s.get("cases", [])
                    if c["outcome"] != "passed"}
    combo_failed = failed_cases(combo)
    for row in combo_failed:
        row["attribution"] = "preexisting_on_parent" if row["node"] in parent_nodes else "introduced_round5"

    parent_failed = failed_cases(parent)

    report = {
        "schema": "cad.d1.round5.regression.v1",
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "guards": {"live_model_calls": 0, "network": "none", "production_code_modified": False},
        "combo": {
            "backend": str(args.combo_backend),
            "head_sha": runner._git(["rev-parse", "HEAD"], args.combo_backend),
            "branch": runner._git(["rev-parse", "--abbrev-ref", "HEAD"], args.combo_backend),
            "status_short": runner._git(["status", "--short"], args.combo_backend),
            "baseline_suites": combo_baseline,
            "round5_suites": combo_round5,
            "baseline_summary": summarize(combo_baseline),
            "round5_summary": summarize(combo_round5),
            "total_summary": summarize(combo),
            "failed_cases": combo_failed,
        },
        "parent": {
            "backend": str(args.parent_backend),
            "head_sha": runner._git(["rev-parse", "HEAD"], args.parent_backend),
            "branch": runner._git(["rev-parse", "--abbrev-ref", "HEAD"], args.parent_backend),
            "suites": parent,
            "summary": summarize(parent),
            "failed_cases": parent_failed,
        },
        "environment": {"python_executable": sys.executable,
                        "versions": runner.package_versions(),
                        "guard": runner.env_guard()},
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8")
    print(json.dumps({
        "combo_baseline": report["combo"]["baseline_summary"],
        "combo_round5": report["combo"]["round5_summary"],
        "parent_summary": report["parent"]["summary"],
        "combo_failed": [(r["group"], r["node"], r["attribution"]) for r in combo_failed],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
