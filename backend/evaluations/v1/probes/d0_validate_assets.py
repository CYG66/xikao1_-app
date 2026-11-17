"""Validate D0 generated assets without model, project or candidate access."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3]
V1 = BACKEND / "evaluations" / "v1"
PROBES = V1 / "probes"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_sha256(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    failures: list[str] = []
    registry = load(V1 / "case_registry.json")
    schema = load(V1 / "evaluation_schema.json")
    replay = load(V1 / "mock_replay_results.json")
    frozen = load(BACKEND / "evaluations" / "p1.3e_dual_case_frozen.json")

    cases = registry.get("cases") or []
    ids = [item.get("case_id") for item in cases]
    if len(cases) != 58:
        failures.append(f"registry count {len(cases)} != 58")
    if len(ids) != len(set(ids)):
        failures.append("duplicate case_id in registry")
    if registry["source_files"]["benchmark_core6"]["case_count"] != 6:
        failures.append("core6 count mismatch")
    if registry["source_files"]["benchmark_extended55"]["case_count"] != 55:
        failures.append("extended55 count mismatch")

    for key, path_key in (("benchmark_core6", "path"), ("benchmark_extended55", "path")):
        source = registry["source_files"][key]
        path = BACKEND / source[path_key]
        if sha256_bytes(path.read_bytes()) != source["file_sha256"]:
            failures.append(f"{key} file hash mismatch")

    frozen_source = registry["source_files"]["frozen_cases"]
    if sha256_bytes((BACKEND / frozen_source["path"]).read_bytes()) != frozen_source["file_sha256"]:
        failures.append("frozen file hash mismatch")
    if canonical_sha256(frozen["cases"]) != frozen_source["declared_cases_sha256"]:
        failures.append("frozen cases canonical hash mismatch")

    for case_id in ("A9", "S1"):
        entry = next(item for item in cases if item["case_id"] == case_id)
        prompt = frozen["cases"][case_id]["prompt"]
        if hashlib.sha256(prompt.encode("utf-8")).hexdigest() != entry["input_sha256"]:
            failures.append(f"{case_id} prompt hash mismatch")
        if canonical_sha256(frozen["cases"][case_id]) != entry["case_canonical_sha256"]:
            failures.append(f"{case_id} canonical hash mismatch")

    records = replay.get("records") or []
    if len(records) != 59:
        failures.append(f"replay records {len(records)} != 59")
    required = set(schema["required"])
    evidence_modes = set(schema["properties"]["evidence_mode"]["enum"])
    for record in records:
        missing = required - set(record)
        if missing:
            failures.append(f"{record.get('case_id')} missing {sorted(missing)}")
        if record["evidence_mode"] not in evidence_modes:
            failures.append(f"{record['case_id']} bad evidence_mode")
        if record["evidence_mode"] == "live_model":
            failures.append(f"{record['case_id']} unexpectedly live_model")
        if record["model"]["called"]:
            failures.append(f"{record['case_id']} model called")
        if record["version"]["project_persistence"]:
            failures.append(f"{record['case_id']} persisted a project")

    by_id = {item["case_id"]: item for item in records}
    if by_id["A9"]["failure_category"] != "self_intersection":
        failures.append("A9 failure category mismatch")
    if by_id["A9"]["geometry"]["self_intersection_count"] != 1:
        failures.append("A9 self-intersection count mismatch")
    if by_id["S1"]["geometry"]["geometry_hash"] != "d8dd79d2377c908b3fa494c2187f5b453f5f2962ecea10b9d818abdae84aa385":
        failures.append("S1 geometry hash mismatch")
    if by_id["S1"]["geometry"]["continuity"]["max_tangent_delta_deg"] != 0.0:
        failures.append("S1 tangent delta mismatch")
    if by_id["M1"]["final_outcome"] != "not_run":
        failures.append("M1 outcome mismatch")

    report_paths = [
        V1 / "D0_可信基线报告.md",
        V1 / "D0_可信基线审计报告.md",
        V1 / "D0_失败根因分类.md",
    ]
    for path in report_paths:
        if not path.exists() or path.stat().st_size == 0:
            failures.append(f"missing report {path.name}")

    report = (V1 / "D0_可信基线报告.md").read_text(encoding="utf-8")
    for token in (
        "ed11eec19df1b432c9cd070bf7712abc5afbff4e4d54bee6f661814443b911b2",
        "58c7d3cdb8692b0b9cf437b059bc5d7dbef6b78d8e8697a6533cc46b1927c12c",
        "08ee398f0093fb930930de5fbe9a999f300eb2c01a44036776c287717259e50e",
        "ededead5bd734cac0b45b1a0ec9585f7f517083528c4e93d78b6eef475ce4597",
        "57b07f5bcf5563bff8f37193ba015009b76aa484c7a9d7ad7e1bf1ccc07912ab",
    ):
        if token not in report:
            failures.append(f"report missing hash {token[:12]}")

    rule6 = load(PROBES / "rule_benchmark_core6.json")
    rule55 = load(PROBES / "rule_benchmark_extended55.json")
    if rule6["summaries"]["rules"]["passed"] != 0:
        failures.append("core6 passed count mismatch")
    if rule55["summaries"]["rules"]["passed"] != 6:
        failures.append("extended55 passed count mismatch")

    if failures:
        print("FAIL")
        for item in failures:
            print("-", item)
        return 1
    print("D0 assets validated")
    print(json.dumps({
        "cases": len(cases),
        "records": len(records),
        "passed": replay["summary"]["passed"],
        "failed": replay["summary"]["failed"],
        "not_run": replay["summary"]["not_run"],
        "real_model_calls": replay["summary"]["real_model_calls"],
        "project_persistence": replay["summary"]["project_persistence"],
        "candidate_writes": replay["summary"]["candidate_writes"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
