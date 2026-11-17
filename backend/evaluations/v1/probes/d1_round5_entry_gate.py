"""Round-5 entry-gate self-check (zero cost, no network, no model call).

Reads the already-produced round-5 artifacts and the round-4 frozen evidence,
then emits a structured gate snapshot. It does not instantiate any HTTP
client and does not touch production code.

Usage:
    python d1_round5_entry_gate.py --v1-dir <evaluations/v1> \
        --out <probes/d1_round5_gate_snapshot.json>
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import subprocess
import sys

PROTECTED = [
    "D1_round4_budget_ledger.json",
    "round4/A9_case_record.json",
    "round4/A9_raw_responses.jsonl",
    "round4/README.md",
]

BASELINE_COUNTS = {
    "S1-requirement-contract": 7, "S2-plan-component-repair": 26,
    "S3-final-source-contract": 5, "S4-construction-interpreter": 74,
    "S5-candidate-visibility-gate": 7, "executor-construction": 37,
    "B1-topology-detection": 2, "B11-topology-detection": 10,
    "B12-arcspline-detection": 9, "C1-service-mock": 4,
    "C11-two-round-service-mock": 2, "C12-production-loop-mock": 1,
}


def norm_sha256(text: str) -> str:
    return hashlib.sha256(
        text.replace("\r\n", "\n").encode("utf-8")
    ).hexdigest().upper()


def load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v1-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--git-dir", required=False)
    args = ap.parse_args()

    v1 = pathlib.Path(args.v1_dir)
    findings: dict[str, object] = {}

    # 1. Protected evidence unchanged: normalized hash vs recorded values.
    recorded = {
        "D1_round4_budget_ledger.json":
            "D6E66B7A5D774976EB94C52CBD87F784A5405C56B4E8633518397339EEE595CB",
        "round4/A9_case_record.json":
            "6FF6D252D05462EFC53A8E6169AAAF17BEF0CBCAF7B36456F8464C53955928D3",
        "round4/A9_raw_responses.jsonl":
            "4A471C6213B75521CFB65AF01959075895924E2D85729D4106D787438A0B02FF",
        "round4/README.md":
            "B67C208382FA0351A43779252F94E80F0AB17DDA98A1704187C69C85FC29D13C",
    }
    protected: dict[str, object] = {}
    protected_all_ok = True
    for rel in PROTECTED:
        p = v1 / rel
        h = norm_sha256(p.read_text(encoding="utf-8"))
        ok = h == recorded[rel]
        protected_all_ok &= ok
        protected[rel] = {"norm_sha256": h, "recorded": recorded[rel], "unchanged": ok}
    findings["protected_evidence"] = protected

    # 2. Regression snapshot matches baseline per module.
    reg = load(v1 / "probes" / "d1_round5_combo_regression_results.json")
    new_counts = {s["group"]: s["counts"]["passed"] for s in reg["suites"]}
    module_match = {g: new_counts.get(g) == n for g, n in BASELINE_COUNTS.items()}
    findings["regression"] = {
        "modules": reg["counts"]["modules"],
        "passed": reg["counts"]["passed"],
        "failed": reg["counts"]["failed"],
        "errors": reg["counts"]["errors"],
        "per_module_match": module_match,
        "all_match": all(module_match.values()),
        "snapshot_sha256": reg["snapshot_sha256"],
        "head": reg["git"]["head_sha"],
        "real_generation": reg["buckets"]["real_generation"]["outcome"],
    }

    # 3. Fixture disclaimer present and explicitly bucketed.
    fixture = load(v1 / "round5" / "A9_reconstructed_fixture.json")
    findings["fixture"] = {
        "fixture_kind": fixture["fixture_kind"],
        "disclaimer_present": "重建夹具，不是原始响应正文" in fixture["disclaimer"],
        "raw_note_present": "只对下一次真实评测生效"
                            in fixture["raw_responses_permanent_note"]["collector_effective"],
        "attempts": len(fixture["recovery"]["attempts"]),
        "bucket": "reconstructed_fixture (separate from real case results)",
    }

    # 4. Contract suite status: production cases still pending adapter; stub
    #    demo is a separate offline bucket and must not be mixed in.
    suite = load(v1 / "round5" / "contract_suite_status.json")
    stub = suite["offline_stub_demo"]
    findings["contract_suite"] = {
        "total": suite["counts"]["total"],
        "pending_adapter": suite["counts"]["pending_adapter"],
        "evaluated": suite["counts"]["evaluated"],
        "offline_stub_only": stub["scope"] == "offline_stub_only",
        "stub_all_match": stub["all_match"],
        "stub_call_counts": stub["call_counts"],
    }

    # 5. Git discipline: no backend/app modification on this tree.
    git_dir = args.git_dir or str(v1.parents[2])
    app_diff = subprocess.run(
        ["git", "-C", git_dir, "diff", "--name-only", "HEAD", "--", "backend/app"],
        capture_output=True, text=True, check=False,
    ).stdout.strip().splitlines()
    merges = subprocess.run(
        ["git", "-C", git_dir, "log", "--merges", "--oneline"],
        capture_output=True, text=True, check=False,
    ).stdout.strip().splitlines()
    findings["git_discipline"] = {
        "backend_app_modified_files": app_diff,
        "backend_app_zero_diff": not app_diff,
        "merge_commits": merges,
        "no_merge": not merges,
    }

    # 5b. Round-5 combo integration + regression snapshots (produced after the
    # C/A/B handover; offline, zero model calls).
    r5_reg = v1 / "round5" / "regression_results.json"
    if r5_reg.exists():
        reg5 = load(r5_reg)
        findings["round5_regression"] = {
            "combo_head": reg5["combo"]["head_sha"],
            "baseline_summary": reg5["combo"]["baseline_summary"],
            "round5_summary": reg5["combo"]["round5_summary"],
            "parent_head": reg5["parent"]["head_sha"],
            "parent_summary": reg5["parent"]["summary"],
            "failed_cases": [
                {"group": r["group"], "node": r["node"], "attribution": r["attribution"]}
                for r in reg5["combo"]["failed_cases"]
            ],
        }

    r5_int = v1 / "round5" / "integration_results.json"
    if r5_int.exists():
        integ = load(r5_int)
        findings["round5_integration"] = {
            "real_model_calls": integ["real_model_calls"],
            "m3_unit": integ["m3_unit_summary"],
            "m2": integ["m2_summary"],
            "loop": [
                {"case": c["case"], "actual_calls": c["actual_calls"],
                 "expected_calls": c["expected_calls"], "match": c["match"]}
                for c in integ["m3_loop_cases"]
            ],
        }

    r5_gap = v1 / "round5" / "relation_gap_results.json"
    if r5_gap.exists():
        gap = load(r5_gap)
        findings["relation_gap"] = {
            "faithful_no_translation": gap["outcomes"]["faithful_no_translation"]["decision"],
            "mapped_equivalent_to_identical": gap["outcomes"]["mapped_equivalent_to_identical"]["decision"],
            "required_fix": gap["required_fix"],
        }

    # 6. Round-5 zero-cost markers.
    findings["zero_cost"] = {
        "real_model_calls_round5": 0,
        "network_probe": "none issued by D",
        "http_client_instantiated": False,
    }

    gate_pass = bool(
        protected_all_ok
        and findings["regression"]["all_match"]
        and findings["fixture"]["disclaimer_present"]
        and findings["git_discipline"]["backend_app_zero_diff"]
    )

    payload = {
        "schema": "cad.d1.round5.gate.v1",
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "gate_pass": gate_pass,
        "admission_ready": False,
        "admission_blockers": [
            "M3 relation vocabulary aligned in production (C accepts B 'equivalent' or production adapter maps it); harness mapping is not a production contract",
            "A feature-contract schema landed in backend; FC cases and red-line 1 traceability verified against real ledger entries",
            "Preexisting route-count drift (30 vs 26) fixed by router/test owner",
            "B symmetry residual thresholds calibrated; decide whether C needs a dedicated similarity-transform channel",
        ],
        "findings": findings,
    }

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out), "gate_pass": gate_pass,
                      "admission_ready": payload["admission_ready"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
