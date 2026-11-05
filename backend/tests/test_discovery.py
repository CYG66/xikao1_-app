import unittest
from unittest.mock import patch

from app.discovery import RoverDiscoveryService


class RoverDiscoveryServiceTests(unittest.TestCase):
    @patch("app.discovery._local_ip", return_value="192.168.8.23")
    @patch("app.discovery._device_identity", return_value="dashes-01")
    def test_payload_identifies_rover_without_credentials(self, _identity, _ip):
        payload = RoverDiscoveryService(http_port=8100).payload()

        self.assertEqual("dashes_rover", payload["type"])
        self.assertEqual("dashes-01", payload["device_id"])
        self.assertEqual("192.168.8.23", payload["address"])
        self.assertEqual(8100, payload["http_port"])
        serialized = str(payload).lower()
        self.assertNotIn("password", serialized)
        self.assertNotIn("api_key", serialized)

    @patch("app.discovery._local_ip", return_value="192.168.8.23")
    @patch("app.discovery._device_identity", return_value="dashes-01")
    def test_mdns_query_returns_service_records(self, _identity, _ip):
        service = RoverDiscoveryService()

        response = service._mdns_response(b"query:_dashes-rover")

        self.assertIsNotNone(response)
        self.assertIn(b"_dashes-rover", response)
        self.assertIn(b"dashes-01", response.lower())
        self.assertIn(bytes([192, 168, 8, 23]), response)

    def test_unrelated_mdns_query_is_ignored(self):
        service = RoverDiscoveryService()

        self.assertIsNone(service._mdns_response(b"query:_http._tcp.local"))


if __name__ == "__main__":
    unittest.main()
