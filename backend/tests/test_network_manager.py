import subprocess
import unittest
from unittest.mock import patch

from app.network_manager import NetworkManagerAdapter


class NetworkManagerAdapterTests(unittest.TestCase):
    def _adapter(self, responses):
        def runner(command, **_kwargs):
            key = tuple(command[1:])
            return responses[key]

        return NetworkManagerAdapter(runner=runner)

    @patch("app.network_manager.shutil.which", return_value="/usr/bin/nmcli")
    def test_scan_returns_visible_networks_without_credentials(self, _which):
        status_key = ("-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status")
        scan_key = (
            "-t", "--escape", "yes", "-f", "SSID,SIGNAL,SECURITY",
            "device", "wifi", "list", "--rescan", "yes",
        )
        adapter = self._adapter({
            status_key: subprocess.CompletedProcess([], 0, "wlan0:wifi:connected:Car-Setup\n", ""),
            scan_key: subprocess.CompletedProcess([], 0, "Office\\:Guest:82:WPA2\nOpen:35:--\n", ""),
        })

        result = adapter.scan()

        self.assertTrue(result["ok"])
        self.assertEqual("Office:Guest", result["networks"][0]["ssid"])
        self.assertEqual(82, result["networks"][0]["signal"])
        self.assertNotIn("password", str(result))

    @patch("app.network_manager.shutil.which", return_value="/usr/bin/nmcli")
    def test_connection_failure_redacts_password(self, _which):
        status_key = ("-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status")
        connect_key = (
            "device", "wifi", "connect", "Office", "ifname", "wlan0", "password", "secret123",
        )
        adapter = self._adapter({
            status_key: subprocess.CompletedProcess([], 0, "wlan0:wifi:disconnected:--\n", ""),
            connect_key: subprocess.CompletedProcess([], 10, "", "authentication failed: secret123"),
        })

        result = adapter.connect("Office", "secret123", False)

        self.assertFalse(result["ok"])
        self.assertNotIn("secret123", result["message"])
        self.assertIn("***", result["message"])


if __name__ == "__main__":
    unittest.main()
