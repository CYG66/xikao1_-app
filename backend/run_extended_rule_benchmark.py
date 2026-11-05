"""只读运行扩充版 CAD 构造评测（规则路径基线）。

当前环境未配置云端 API Key，RobotAgentService 自动走确定性规则解析器
（生产解释器在未配置模型时注入 None callback）。
本脚本不修改任何现有代码，仅复用 cad_construction_evaluation 的
load/run 函数，将扩充语料逐条送入构造解释器，输出标准评测报告。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from app.agent_service import RobotAgentService
from app.cad_construction_evaluation import (
    run_construction_benchmark,
    load_construction_benchmark,
)

BACKEND = Path(__file__).resolve().parent
CORPUS = BACKEND / "evaluations" / "cad_construction_model_benchmark_extended.json"
REPORT = BACKEND / "evaluations" / "reports" / "cad-construction-rules-extended-20261019.json"


def main() -> int:
    service = RobotAgentService(restore_pending_actions=False)
    print(f"configured={getattr(service, 'configured', 'N/A')} "
          f"api_keys={list(service.api_keys)} mode={service.mode}")

    def runner(provider: str, command: str) -> dict:
        return service._interpret_cad_construction_plan(command, mode="advanced")

    corpus = load_construction_benchmark(CORPUS)
    report = run_construction_benchmark(["rules"], runner, corpus)

    # 逐条打印
    print(f"\n=== 逐条结果（{len(corpus['cases'])} 条）===")
    for item in report["results"]:
        checks_failed = [k for k, v in item["checks"].items() if not v]
        status = item["status"]
        parser = item["parser"]
        err = item["error"] or ""
        mark = "PASS" if item["passed"] else "FAIL"
        print(f"[{mark}] {item['case_id']:<36} {status:<22} {str(parser):<20} "
              f"entities={item['metrics']['entity_count']:<3} "
              f"failed={','.join(checks_failed) if checks_failed else '-'}")
        if err and status != "ready":
            print(f"      err: {err[:120]}")

    print("\n=== 汇总 ===")
    print(json.dumps(report["summaries"], ensure_ascii=False, indent=2))

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告已写入：{REPORT.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
