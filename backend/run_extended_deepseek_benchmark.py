"""临时评测脚本：DeepSeek 模型路径跑 55 条扩充语料（不改任何现有代码）。

依赖环境变量 DEEPSEEK_API_KEY（由调用方注入）。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from app.agent_service import RobotAgentService
from app.cad_construction_evaluation import (
    evaluate_construction_interpretation,
    load_construction_benchmark,
    run_construction_benchmark,
)

BACKEND = Path(__file__).resolve().parent
CORPUS = BACKEND / "evaluations" / "cad_construction_model_benchmark_extended.json"
REPORT = BACKEND / "evaluations" / "reports" / "cad-construction-deepseek-extended-20261019.json"


def main() -> int:
    service = RobotAgentService(restore_pending_actions=False)
    print(f"configured={service.configured} mode={service.mode} "
          f"advanced_model={service.advanced_model} "
          f"api_keys={list(service.api_keys)}")

    def runner(provider: str, command: str) -> dict:
        return evaluate_construction_interpretation(
            service, command, mode="advanced", force_structured_model=True,
        )

    corpus = load_construction_benchmark(CORPUS)
    started = time.perf_counter()
    report = run_construction_benchmark(["deepseek"], runner, corpus)
    wall = round(time.perf_counter() - started, 1)

    print(f"\n=== 逐条结果（{len(corpus['cases'])} 条，总耗时 {wall}s）===")
    for item in report["results"]:
        checks_failed = [k for k, v in item["checks"].items() if not v]
        mark = "PASS" if item["passed"] else "FAIL"
        print(f"[{mark}] {item['case_id']:<36} {item['status']:<22} "
              f"{str(item['parser']):<20} entities={item['metrics']['entity_count']:<3} "
              f"attempted={str(item['provider_attempted']):<5} "
              f"ms={item['metrics']['latency_ms']:<8.0f} "
              f"failed={','.join(checks_failed) if checks_failed else '-'}")
        if item["error"] and item["status"] != "ready":
            print(f"      err: {item['error'][:120]}")

    print("\n=== 汇总 ===")
    print(json.dumps(report["summaries"], ensure_ascii=False, indent=2))

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告已写入：{REPORT.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
