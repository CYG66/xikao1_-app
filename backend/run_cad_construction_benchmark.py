from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

from app.agent_service import RobotAgentService
from app.agent_service_config import DEFAULT_MODELS, PROVIDER_MODEL_ENV, PROVIDERS
from app.cad_construction_evaluation import (
    DEFAULT_CONSTRUCTION_BENCHMARK_PATH,
    evaluate_construction_interpretation,
    load_construction_benchmark,
    run_construction_benchmark,
)


def _configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="隔离运行通用自然语言二维 CAD 生成评测，不创建项目或候选方案。"
    )
    parser.add_argument(
        "--providers", nargs="*", choices=sorted(PROVIDERS),
        help="要评测的供应商；省略时使用本机已配置的全部供应商。",
    )
    parser.add_argument(
        "--corpus", type=Path, default=DEFAULT_CONSTRUCTION_BENCHMARK_PATH,
        help="评测集 JSON 路径。",
    )
    parser.add_argument(
        "--output", type=Path,
        help="可选报告输出路径；报告不包含 API Key。",
    )
    parser.add_argument(
        "--force-structured-model", action="store_true",
        help="绕过规则解析，只测试 structured_model（路径3）。",
    )
    return parser.parse_args()


def main() -> int:
    _configure_console_encoding()
    args = _arguments()
    service = RobotAgentService(restore_pending_actions=False)
    providers = args.providers or sorted(service.api_keys)
    if not providers:
        print("没有已配置的云端模型。请先在 App 中保存模型 API 配置。", file=sys.stderr)
        return 2
    missing = [provider for provider in providers if not service.api_keys.get(provider)]
    if missing:
        print(f"以下供应商没有 API Key：{', '.join(missing)}", file=sys.stderr)
        return 2

    def runner(provider: str, command: str) -> dict:
        service.mode = provider
        env_name = PROVIDER_MODEL_ENV[provider]
        service.model = os.getenv(env_name, DEFAULT_MODELS[provider]).strip()
        service.base_model = service.model
        service.advanced_model = service.model
        return evaluate_construction_interpretation(
            service,
            command,
            mode="advanced",
            force_structured_model=args.force_structured_model,
        )

    corpus = deepcopy(load_construction_benchmark(args.corpus))
    if args.force_structured_model:
        for case in corpus["cases"]:
            expected = case.setdefault("expected", {})
            expected["required_parser"] = "structured_model"
            expected["require_provider_attempted"] = True

    report = run_construction_benchmark(
        providers,
        runner,
        corpus,
    )
    report["execution_mode"] = (
        "forced_structured_model"
        if args.force_structured_model
        else "production_rule_first"
    )
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
        print(f"报告已写入：{args.output.resolve()}")
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
