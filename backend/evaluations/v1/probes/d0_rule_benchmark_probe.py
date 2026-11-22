"""D0 zero-cost rule benchmark probe.

Runs the repository's 6-case and 55-case construction benchmarks through the
deterministic rule interpreter only. No provider callback, credentials, model
call, project persistence, or candidate write is involved.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.cad_construction_evaluation import (
    load_construction_benchmark,
    run_construction_benchmark,
)
from app.cad_construction_interpreter import interpret_construction_request

OUT_DIR = Path(__file__).resolve().parent


def runner(_provider: str, command: str) -> dict:
    return interpret_construction_request(command, None)


def run(path: Path, output: Path) -> dict:
    corpus = load_construction_benchmark(path)
    report = run_construction_benchmark(["rules"], runner, corpus)
    report["evidence_mode"] = "rule_parser_zero_cost"
    report["model_callback"] = None
    report["corpus_path"] = path.relative_to(BACKEND).as_posix()
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    outputs = {}
    for name, path in (
        ("core6", BACKEND / "evaluations" / "cad_construction_model_benchmark.json"),
        ("extended55", BACKEND / "evaluations" / "cad_construction_model_benchmark_extended.json"),
    ):
        report = run(path, OUT_DIR / f"rule_benchmark_{name}.json")
        outputs[name] = {
            "case_count": report["case_count"],
            "summary": report["summaries"]["rules"],
            "output": (OUT_DIR / f"rule_benchmark_{name}.json").name,
        }
    print(json.dumps({"schema": "cad.d0.rule-benchmark-probe.v1", **outputs},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
