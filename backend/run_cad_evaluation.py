from __future__ import annotations

import json
import sys

from app.agent_evaluation import DEFAULT_CAD_CORPUS_PATH, run_policy_evaluation
from app.agent_service import RobotAgentService


def main() -> int:
    service = object.__new__(RobotAgentService)

    def safe_resolve(message: str, mode: str, history: list[dict[str, str]]):
        service.mode = "local"
        service.api_keys = {}
        return service.resolve_intent(message, mode, history)

    result = run_policy_evaluation(
        service.route_intent,
        service._selected_deepseek_tools,
        safe_resolve,
        DEFAULT_CAD_CORPUS_PATH,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
