from __future__ import annotations

import unittest
from unittest.mock import patch

from app.user_request_limits import UserRequestLimitError, UserRequestLimiter


class UserRequestLimiterTest(unittest.TestCase):
    def test_same_user_is_limited_but_other_users_are_independent(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "XLINE_AGENT_USER_MAX_CONCURRENT_REQUESTS": "1",
                "XLINE_AGENT_USER_QUEUE_TIMEOUT_SECONDS": "0.1",
            },
        ):
            limiter = UserRequestLimiter()

        with limiter.acquire("user-a"):
            with limiter.acquire("user-b"):
                pass
            with self.assertRaises(UserRequestLimitError):
                with limiter.acquire("user-a"):
                    pass

        # The context manager must release the slot even after a rejected wait.
        with limiter.acquire("user-a"):
            pass

    def test_invalid_environment_values_are_clamped(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "XLINE_AGENT_USER_MAX_CONCURRENT_REQUESTS": "999",
                "XLINE_AGENT_USER_QUEUE_TIMEOUT_SECONDS": "-5",
            },
        ):
            limiter = UserRequestLimiter()
        self.assertEqual(16, limiter.limit)
        self.assertEqual(0.1, limiter.acquire_timeout)


if __name__ == "__main__":
    unittest.main()
