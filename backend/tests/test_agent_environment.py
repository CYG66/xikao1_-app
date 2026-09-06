from __future__ import annotations

import unittest
from unittest.mock import patch

from app.agent_service import RobotAgentService


class AgentEnvironmentTest(unittest.TestCase):
    def test_deepseek_environment_is_loaded_for_default_provider(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {
                    "XLINE_AGENT_PROVIDER": "deepseek",
                    "DEEPSEEK_API_KEY": "test-deepseek-key",
                    "DEEPSEEK_MODEL": "deepseek-chat",
                },
                clear=False,
            ),
            patch.object(RobotAgentService, "_load_config"),
            patch.object(RobotAgentService, "_restore_pending_actions"),
        ):
            service = RobotAgentService()

        self.assertEqual(service.mode, "deepseek")
        self.assertEqual(service.model, "deepseek-chat")
        self.assertEqual(service.api_key, "test-deepseek-key")
        self.assertTrue(service.configured)


if __name__ == "__main__":
    unittest.main()
