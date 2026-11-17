"""Round-5 fixture builder: reconstruct an A9 fixture from saved parsed plans.

Zero-cost, offline. The built fixture is explicitly labeled as a
**reconstructed fixture, not the original response body**; it must not be
presented as recovered raw model output. Existing raw responses are never
rewritten or backfilled.

Usage:
    python d1_round5_build_fixture.py --v1-dir <evaluations/v1>
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
from typing import Any

ATTEMPT_KEYS = [
    "attempt", "status", "confidence", "category", "error", "plan",
    "plan_sha256", "changed_plan_fields", "step_diff",
]


def _pick(source: dict[str, Any]) -> dict[str, Any]:
    return {k: source[k] for k in ATTEMPT_KEYS if k in source}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v1-dir", required=True)
    args = ap.parse_args()
    v1 = pathlib.Path(args.v1_dir).resolve()

    record = json.loads((v1 / "round4" / "A9_case_record.json").read_text(encoding="utf-8"))
    raw_path = v1 / "round4" / "A9_raw_responses.jsonl"
    raw_lines = raw_path.read_text(encoding="utf-8").splitlines()
    raw_bytes = raw_path.stat().st_size

    recovery = record["result_redacted"]["construction_interpretation"]["recovery"]
    attempts = [_pick(a) for a in recovery.get("attempts", [])]

    fixture: dict[str, Any] = {
        "fixture_kind": "reconstructed_fixture",
        "disclaimer": (
            "重建夹具，不是原始响应正文。本文件由第四轮已保存的解析后计划 "
            "（plan）与后端验收记录重建，不包含、也不伪装为模型原始响应正文；"
            "不得作为原始响应证据使用。"
        ),
        "source_evidence": {
            "case_id": record["record"]["case_id"],
            "original_input": record["record"]["original_input"],
            "input_sha256": record["record"]["input_sha256"],
            "source_case_record": "round4/A9_case_record.json",
            "source_raw_responses": "round4/A9_raw_responses.jsonl",
            "model": record["record"]["model"],
            "request_count": record["record"]["request_count"],
        },
        "raw_responses_permanent_note": {
            "existing_raw_file": "round4/A9_raw_responses.jsonl",
            "existing_raw_lines": len(raw_lines),
            "existing_raw_bytes": raw_bytes,
            "scope": "现有 raw_responses 仅保存响应侧元数据：request_id、model、"
                     "finish_reason、usage；未保存请求 payload 与响应正文内容。",
            "collector_effective": "新隔离采集器只对下一次真实评测生效，不回填本文件。",
        },
        "recovery": {
            "schema": recovery.get("schema"),
            "source_sha256": recovery.get("source_sha256"),
            "max_repairs": recovery.get("max_repairs"),
            "repair_count": recovery.get("repair_count"),
            "attempts": attempts,
        },
        "reconstruction_provenance": {
            "built_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "builder": "probes/d1_round5_build_fixture.py",
            "note": "解析后计划与后端验收特征来自冻结案例记录；重建过程不触网、不调用模型。",
        },
    }

    out_dir = v1 / "round5"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "A9_reconstructed_fixture.json"
    out.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "fixture": str(out),
        "attempts": len(attempts),
        "raw_lines": len(raw_lines),
        "raw_bytes": raw_bytes,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
