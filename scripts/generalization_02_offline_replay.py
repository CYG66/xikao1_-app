"""Frozen-output offline replay for CAD-CORE-GENERALIZATION-02.

Reads the 20 recorded GENERALIZATION-01 runs, rebuilds source acceptance with
the current production code, and writes a machine-readable before/after matrix.
No model, network, hardware or database is touched.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from pathlib import Path

WORKTREE = Path(r"C:\Users\29924\Codes\worktrees\core-generalization-02")
SOURCE = Path(r"C:\Users\29924\Codes\xikao\cad_e2e_generalization_live_01")
OUTPUT = Path(r"C:\Users\29924\Codes\xikao\cad_core_generalization_02")
sys.path.insert(0, str(WORKTREE / "backend"))

from app.cad_construction_commit import _rebind_source_acceptance  # noqa: E402

CASES = [
    "B01", "B02", "B03", "B04", "M01", "M02", "M03", "M04",
    "F01", "F02", "F03", "F04", "T01", "T02", "T03", "T04",
    "Q01", "Q02", "Q03", "Q04",
]
REJECTED = ["B04", "M01", "M02", "M03", "M04", "F01", "T01", "T04"]
MUST_STAY_PARTIAL = ["F03", "T02"]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def replay_case(case_id: str) -> dict:
    run_dir = SOURCE / "runs" / "GENERALIZATION-01" / case_id
    recorded_path = run_dir / "service-step-1.json"
    if not recorded_path.exists():
        return {
            "case_id": case_id,
            "status": "not_replayable_no_candidate",
            "requirement_coverage": None,
            "verified_checks": None,
            "unknown_checks": None,
            "source_status": None,
            "geometry_hash_before": None,
            "geometry_hash_after": None,
            "geometry_hash_unchanged": True,
            "clauses": [],
            "blocking_requirements": [],
            "evidence_sha256": None,
        }
    recorded = _load(recorded_path)
    variant = recorded.get("variant")
    if variant is None and recorded.get("variants"):
        variant = recorded["variants"][0]
    if variant is None or not variant.get("construction_record"):
        return {
            "case_id": case_id,
            "status": "not_replayable_no_candidate",
            "requirement_coverage": None,
            "verified_checks": None,
            "unknown_checks": None,
            "source_status": None,
            "geometry_hash_before": None,
            "geometry_hash_after": None,
            "geometry_hash_unchanged": True,
            "clauses": [],
            "blocking_requirements": [],
            "evidence_sha256": None,
        }
    record = variant["construction_record"]
    geometry_before = record.get("geometry_hash")
    interpretation = {
        "source_acceptance": copy.deepcopy(record["source_acceptance"]),
        "plan": copy.deepcopy(record.get("plan")),
        "preflight_structure": None,
        "structure_contract": copy.deepcopy(record.get("structure_contract")),
        "structure_validation": copy.deepcopy(record.get("structure_validation")),
        "composition_contract": copy.deepcopy(record.get("composition_contract")),
        "composition_validation": copy.deepcopy(record.get("composition_validation")),
    }
    candidate = {
        "trial_result": {
            "plan": record.get("plan"),
            "logical_objects": variant["logical_objects"],
            "geometries": variant["geometries"],
            "symbol_table": record.get("symbol_table"),
            "feasibility": record.get("feasibility"),
        }
    }
    _rebind_source_acceptance(
        recorded["project"]["original_prompt"],
        interpretation,
        candidate,
        recorded["project"],
        project_created_in_commit=False,
        prior_variant_count=0,
        candidate_write_in_commit=True,
        write_receipt=record.get("write_receipt"),
    )
    acceptance = interpretation.get("acceptance_summary") or {}
    source = interpretation["source_acceptance"]
    clauses = [
        {
            "requirement_id": item.get("requirement_id"),
            "requirement": item.get("requirement"),
            "status": item.get("status"),
            "reason": item.get("reason"),
            "evidence": item.get("evidence"),
            "unsupported_evidence": item.get("unsupported_evidence"),
            "binding": item.get("binding"),
        }
        for item in (source.get("coverage_evidence") or {}).get("clauses", [])
    ]
    return {
        "case_id": case_id,
        "status": acceptance.get("status") or "no_acceptance_summary",
        "requirement_coverage": acceptance.get("requirement_coverage"),
        "verified_checks": acceptance.get("verified_checks"),
        "unknown_checks": acceptance.get("unknown_checks"),
        "source_status": source.get("status"),
        "geometry_hash_before": geometry_before,
        "geometry_hash_after": record.get("geometry_hash"),
        "geometry_hash_unchanged": geometry_before == record.get("geometry_hash"),
        "clauses": clauses,
        "blocking_requirements": source.get("blocking_requirements", []),
        "evidence_sha256": _hash({"acceptance": acceptance, "source": source}),
    }


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    metrics = _load(SOURCE / "metrics.json")
    before = {item["case_id"]: item for item in metrics["cases"]}
    results = [replay_case(case_id) for case_id in CASES]
    after = {item["case_id"]: item for item in results}

    for case_id in REJECTED:
        assert after[case_id]["status"] == "passed", (case_id, after[case_id])
        assert after[case_id]["requirement_coverage"] == "complete", case_id
        assert after[case_id]["geometry_hash_unchanged"], case_id
    for case_id in MUST_STAY_PARTIAL:
        assert after[case_id]["status"] != "passed", (case_id, after[case_id])
    assert not any(item["status"] == "passed" and not item["geometry_hash_unchanged"] for item in results)

    matrix = []
    for case_id in CASES:
        old = before[case_id]
        new = after[case_id]
        matrix.append({
            "case_id": case_id,
            "formal_before": old.get("formal_status"),
            "formal_after": new["status"],
            "coverage_before": old.get("requirement_coverage"),
            "coverage_after": new["requirement_coverage"],
            "verified_before": old.get("verified_clauses"),
            "verified_after": new["verified_checks"],
            "unverified_before": old.get("unverified_clauses"),
            "total_clauses": old.get("total_clauses"),
            "geometry_ok": old.get("strict_geometry_ok"),
            "geometry_hash_unchanged": new["geometry_hash_unchanged"],
        })

    payload = {
        "schema": "cad.generalization-02.offline-replay.v1",
        "baseline_commit": "69fd75dab4a0f3a925e95da3098c0bdaabb83c58",
        "frozen_report_sha256": "1f14955918dca491ca9f1bbaa8a671d9867e0147ed65d880d9f39e8aa5088969",
        "model_requests": 0,
        "cases": results,
        "matrix": matrix,
        "summary": {
            "recovered_formal_pass": sum(
                1 for case_id in REJECTED if after[case_id]["status"] == "passed"
            ),
            "recovered_target": len(REJECTED),
            "false_acceptance": sum(
                1 for case_id in MUST_STAY_PARTIAL if after[case_id]["status"] == "passed"
            ),
            "geometry_hashes_changed": sum(
                1 for item in results if not item["geometry_hash_unchanged"]
            ),
        },
    }
    (OUTPUT / "offline_replay.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# CAD-CORE-GENERALIZATION-02 冻结输出离线重放",
        "",
        "真实模型请求：0；输入为 GENERALIZATION-01 已冻结的 `service-step-1.json`。",
        "",
        "| 案例 | 重放前 | 重放后 | 覆盖 | 验证条款 | 几何哈希 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in matrix:
        lines.append(
            f"| {row['case_id']} | {row['formal_before']} | {row['formal_after']} | "
            f"{row['coverage_after']} | {row['verified_after']} | "
            f"{'不变' if row['geometry_hash_unchanged'] else '变化'} |"
        )
    lines += [
        "",
        f"- 八例误拒恢复：{payload['summary']['recovered_formal_pass']}/8",
        f"- F03/T02 误接受：{payload['summary']['false_acceptance']}",
        f"- 几何哈希变化：{payload['summary']['geometry_hashes_changed']}",
    ]
    (OUTPUT / "offline_replay.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
