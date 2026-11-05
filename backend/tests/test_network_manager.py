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
        saved_key = (
            "-t", "--escape", "yes", "-f", "NAME,TYPE", "connection", "show",
        )
        adapter = self._adapter({
            status_key: subprocess.CompletedProcess([], 0, "wlan0:wifi:connected:Car-Setup\n", ""),
            scan_key: subprocess.CompletedProcess([], 0, "Office\\:Guest:82:WPA2\nOpen:35:--\n", ""),
            saved_key: subprocess.CompletedProcess([], 0, "Office\\:Guest:wifi\n", ""),
        })

        result = adapter.scan()

        self.assertTrue(result["ok"])
        self.assertEqual("Office:Guest", result["networks"][0]["ssid"])
        self.assertEqual(82, result["networks"][0]["signal"])
        self.assertEqual("Office:Guest", result["saved_networks"][0]["ssid"])
        self.assertEqual("saved", result["networks"][0]["connection_state"])
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

    @patch("app.network_manager.shutil.which", return_value="/usr/bin/nmcli")
    def test_disconnect_only_active_matching_interface(self, _which):
        status_key = ("-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status")
        disconnect_key = ("device", "disconnect", "ifname", "wlan0")
        adapter = self._adapter({
            status_key: subprocess.CompletedProcess([], 0, "wlan0:wifi:connected:Office\n", ""),
            disconnect_key: subprocess.CompletedProcess([], 0, "", ""),
        })

        result = adapter.disconnect("Office")

        self.assertTrue(result["ok"])
        self.assertEqual("Office", result["ssid"])

    @patch("app.network_manager.shutil.which", return_value="/usr/bin/nmcli")
    def test_disconnect_rejects_non_active_ssid(self, _which):
        status_key = ("-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status")
        adapter = self._adapter({
            status_key: subprocess.CompletedProcess([], 0, "wlan0:wifi:connected:Office\n", ""),
        })

        result = adapter.disconnect("Other")

        self.assertFalse(result["ok"])
        self.assertEqual("profile_not_active", result["error_code"])

    @patch("app.network_manager.shutil.which", return_value="/usr/bin/nmcli")
    def test_forget_deletes_saved_profile_without_credentials(self, _which):
        saved_key = ("-t", "--escape", "yes", "-f", "NAME,TYPE", "connection", "show")
        delete_key = ("connection", "delete", "id", "Office")
        adapter = self._adapter({
            saved_key: subprocess.CompletedProcess([], 0, "Office:wifi\n", ""),
            delete_key: subprocess.CompletedProcess([], 0, "", ""),
        })

        result = adapter.forget("Office")

        self.assertTrue(result["ok"])
        self.assertNotIn("password", str(result).lower())

    @patch("app.network_manager.shutil.which", return_value="/usr/bin/nmcli")
    def test_forget_rejects_unknown_profile(self, _which):
        saved_key = ("-t", "--escape", "yes", "-f", "NAME,TYPE", "connection", "show")
        adapter = self._adapter({
            saved_key: subprocess.CompletedProcess([], 0, "Office:wifi\n", ""),
        })

        result = adapter.forget("Other")

        self.assertFalse(result["ok"])
        self.assertEqual("profile_not_found", result["error_code"])

    @patch("app.network_manager.shutil.which", return_value="/usr/bin/nmcli")
    def test_connect_saved_uses_profile_without_password(self, _which):
        status_key = ("-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status")
        details_key = (
            "-t", "--escape", "yes", "-f",
            "GENERAL.CONNECTION,GENERAL.STATE,IP4.ADDRESS[1],IP4.GATEWAY,WIFI.SIGNAL,GENERAL.CONNECTION-TIMESTAMP",
            "device", "show", "wlan0",
        )
        saved_key = ("-t", "--escape", "yes", "-f", "NAME,TYPE", "connection", "show")
        up_key = ("connection", "up", "id", "Office", "ifname", "wlan0")
        responses = {
            status_key: subprocess.CompletedProcess([], 0, "wlan0:wifi:connected:Office\n", ""),
            details_key: subprocess.CompletedProcess([], 0, "GENERAL.CONNECTION:Office\nIP4.ADDRESS[1]:192.168.0.100/24\nIP4.GATEWAY:192.168.0.1\nWIFI.SIGNAL:80\nGENERAL.CONNECTION-TIMESTAMP:2026-09-14T10:00:00\n", ""),
            saved_key: subprocess.CompletedProcess([], 0, "Office:wifi\n", ""),
            up_key: subprocess.CompletedProcess([], 0, "", ""),
        }
        adapter = self._adapter(responses)

        result = adapter.connect_saved("Office")

        self.assertTrue(result["ok"])
        self.assertNotIn("password", str(result).lower())

    @patch("app.network_manager.shutil.which", return_value="/usr/bin/nmcli")
    def test_verify_returns_rover_network_details(self, _which):
        status_key = ("-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status")
        details_key = (
            "-t", "--escape", "yes", "-f",
            "GENERAL.CONNECTION,GENERAL.STATE,IP4.ADDRESS[1],IP4.GATEWAY,WIFI.SIGNAL,GENERAL.CONNECTION-TIMESTAMP",
            "device", "show", "wlan0",
        )
        adapter = self._adapter({
            status_key: subprocess.CompletedProcess([], 0, "wlan0:wifi:connected:Office\n", ""),
            details_key: subprocess.CompletedProcess([], 0, "GENERAL.CONNECTION:Office\nIP4.ADDRESS[1]:192.168.0.100/24\nIP4.GATEWAY:192.168.0.1\nWIFI.SIGNAL:80\nGENERAL.CONNECTION-TIMESTAMP:2026-09-14T10:00:00\n", ""),
        })

        result = adapter.verify("Office")

        self.assertTrue(result["verified"])
        self.assertEqual("192.168.0.100", result["ip_address"])
        self.assertEqual("192.168.0.1", result["gateway"])
        self.assertEqual(80, result["signal"])

    @patch("app.network_manager.shutil.which", return_value="/usr/bin/nmcli")
    def test_connect_defers_ip_assignment_check_to_verify(self, _which):
        status_key = ("-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status")
        details_key = (
            "-t", "--escape", "yes", "-f",
            "GENERAL.CONNECTION,GENERAL.STATE,IP4.ADDRESS[1],IP4.GATEWAY,WIFI.SIGNAL,GENERAL.CONNECTION-TIMESTAMP",
            "device", "show", "wlan0",
        )
        connect_key = (
            "device", "wifi", "connect", "Office", "ifname", "wlan0", "password", "secret123",
        )
        adapter = self._adapter({
            status_key: subprocess.CompletedProcess([], 0, "wlan0:wifi:connected:Office\n", ""),
            details_key: subprocess.CompletedProcess([], 0, "GENERAL.CONNECTION:Office\nIP4.ADDRESS[1]:\nIP4.GATEWAY:\nWIFI.SIGNAL:65\n", ""),
            connect_key: subprocess.CompletedProcess([], 0, "", ""),
        })

        result = adapter.connect("Office", "secret123", False)

        self.assertTrue(result["ok"])
        self.assertTrue(result["switching"])


if __name__ == "__main__":
    unittest.main()
