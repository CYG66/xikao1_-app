import unittest

from app.agent_failure_policy import classify_agent_failure


class AgentFailurePolicyTests(unittest.TestCase):
    def test_missing_target_requires_user_clarification(self) -> None:
        result = classify_agent_failure(["target_resolved"])
        self.assertEqual(result["category"], "input_clarification")
        self.assertEqual(result["next_action"], "ask_user")
        self.assertTrue(result["user_action_required"])

    def test_version_conflict_is_refreshable(self) -> None:
        result = classify_agent_failure(["version_binding"])
        self.assertEqual(result["next_action"], "refresh_and_replan")
        self.assertTrue(result["retryable"])

    def test_geometry_integrity_fails_closed(self) -> None:
        result = classify_agent_failure(["non_target_integrity"])
        self.assertEqual(result["category"], "geometry_validation")
        self.assertFalse(result["retryable"])

    def test_unsupported_message_is_not_retried(self) -> None:
        result = classify_agent_failure([], message="当前不支持布尔合并")
        self.assertEqual(result["category"], "unsupported_operation")
        self.assertFalse(result["retryable"])


if __name__ == "__main__":
    unittest.main()
