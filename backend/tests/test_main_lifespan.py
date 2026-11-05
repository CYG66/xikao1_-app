from __future__ import annotations

import unittest
from unittest.mock import patch

from app.main import app, lifespan


class MainLifespanTest(unittest.IsolatedAsyncioTestCase):
    async def test_starts_and_stops_services_in_existing_order(self) -> None:
        events: list[str] = []
        with (
            patch("app.main.ros_adapter.start", side_effect=lambda: events.append("ros_start")),
            patch("app.main.ros_adapter.stop", side_effect=lambda: events.append("ros_stop")),
            patch(
                "app.main.creative_project_sync.start",
                side_effect=lambda: events.append("sync_start"),
            ),
            patch(
                "app.main.creative_project_sync.stop",
                side_effect=lambda: events.append("sync_stop"),
            ),
            patch(
                "app.main.rover_discovery.start",
                side_effect=lambda: events.append("discovery_start"),
            ),
            patch(
                "app.main.rover_discovery.stop",
                side_effect=lambda: events.append("discovery_stop"),
            ),
            patch.dict("os.environ", {"XLINE_EMBEDDED_DISCOVERY": "1"}),
        ):
            async with lifespan(app):
                self.assertEqual(
                    events, ["ros_start", "sync_start", "discovery_start"]
                )

        self.assertEqual(
            events,
            [
                "ros_start",
                "sync_start",
                "discovery_start",
                "discovery_stop",
                "sync_stop",
                "ros_stop",
            ],
        )

    async def test_discovery_can_remain_disabled(self) -> None:
        events: list[str] = []
        with (
            patch("app.main.ros_adapter.start", side_effect=lambda: events.append("ros_start")),
            patch("app.main.ros_adapter.stop", side_effect=lambda: events.append("ros_stop")),
            patch(
                "app.main.creative_project_sync.start",
                side_effect=lambda: events.append("sync_start"),
            ),
            patch(
                "app.main.creative_project_sync.stop",
                side_effect=lambda: events.append("sync_stop"),
            ),
            patch("app.main.rover_discovery.start") as discovery_start,
            patch("app.main.rover_discovery.stop") as discovery_stop,
            patch.dict("os.environ", {"XLINE_EMBEDDED_DISCOVERY": "0"}),
        ):
            async with lifespan(app):
                pass

        discovery_start.assert_not_called()
        discovery_stop.assert_not_called()
        self.assertEqual(
            events, ["ros_start", "sync_start", "sync_stop", "ros_stop"]
        )

    async def test_startup_failure_cleans_up_already_initialized_services(self) -> None:
        events: list[str] = []

        def fail_sync_start() -> None:
            events.append("sync_start")
            raise RuntimeError("sync startup failed")

        with (
            patch("app.main.ros_adapter.start", side_effect=lambda: events.append("ros_start")),
            patch("app.main.ros_adapter.stop", side_effect=lambda: events.append("ros_stop")),
            patch("app.main.creative_project_sync.start", side_effect=fail_sync_start),
            patch(
                "app.main.creative_project_sync.stop",
                side_effect=lambda: events.append("sync_stop"),
            ),
            patch("app.main.rover_discovery.start") as discovery_start,
            patch("app.main.rover_discovery.stop") as discovery_stop,
        ):
            with self.assertRaisesRegex(RuntimeError, "sync startup failed"):
                async with lifespan(app):
                    self.fail("lifespan must not enter after startup failure")

        discovery_start.assert_not_called()
        discovery_stop.assert_not_called()
        self.assertEqual(
            events, ["ros_start", "sync_start", "sync_stop", "ros_stop"]
        )
