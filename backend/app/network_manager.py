"""Restricted NetworkManager adapter for rover Wi-Fi provisioning.

The API never accepts shell commands and never returns or logs Wi-Fi secrets.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any, Callable


class NetworkManagerAdapter:
    def __init__(
        self,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self._runner = runner

    @staticmethod
    def _split_terse(line: str) -> list[str]:
        values: list[str] = []
        value: list[str] = []
        escaped = False
        for character in line:
            if escaped:
                value.append(character)
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == ":":
                values.append("".join(value))
                value = []
            else:
                value.append(character)
        if escaped:
            value.append("\\")
        values.append("".join(value))
        return values

    @staticmethod
    def _message(result: subprocess.CompletedProcess[str]) -> str:
        text = (result.stderr or result.stdout or "").strip()
        return text.splitlines()[-1] if text else "NetworkManager 未返回状态"

    def _run(
        self, arguments: list[str], timeout: float = 15.0
    ) -> subprocess.CompletedProcess[str]:
        return self._runner(
            ["nmcli", *arguments],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def _wireless_devices(self) -> list[dict[str, str]]:
        result = self._run(
            ["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"]
        )
        if result.returncode != 0:
            return []
        devices: list[dict[str, str]] = []
        for line in result.stdout.splitlines():
            values = self._split_terse(line)
            if len(values) < 4 or values[1] != "wifi":
                continue
            device = {
                "interface": values[0],
                "state": values[2],
                "connection": values[3],
            }
            try:
                details = self._run(
                    [
                        "-t",
                        "--escape",
                        "yes",
                        "-f",
                        "GENERAL.CONNECTION,GENERAL.STATE,IP4.ADDRESS[1],IP4.GATEWAY,WIFI.SIGNAL,GENERAL.CONNECTION-TIMESTAMP",
                        "device",
                        "show",
                        values[0],
                    ]
                )
                if details.returncode == 0:
                    for detail_line in details.stdout.splitlines():
                        key, _, value = detail_line.partition(":")
                        if key == "GENERAL.CONNECTION":
                            device["connection"] = value
                        elif key == "GENERAL.STATE":
                            device["state_detail"] = value
                        elif key == "IP4.ADDRESS[1]":
                            device["ip_address"] = value.split("/")[0]
                        elif key == "IP4.GATEWAY":
                            device["gateway"] = value
                        elif key == "WIFI.SIGNAL":
                            device["signal"] = value
                        elif key == "GENERAL.CONNECTION-TIMESTAMP":
                            device["connected_since"] = value
            except (KeyError, OSError, subprocess.SubprocessError):
                pass
            devices.append(device)
        return devices

    def _saved_wifi_profiles(self) -> set[str]:
        """Return saved Wi-Fi profile names without exposing credentials."""
        result = self._run(
            [
                "-t",
                "--escape",
                "yes",
                "-f",
                "NAME,TYPE",
                "connection",
                "show",
            ]
        )
        if result.returncode != 0:
            return set()
        return {
            values[0]
            for line in result.stdout.splitlines()
            for values in [self._split_terse(line)]
            if len(values) >= 2
            and values[0]
            and values[1] in {"wifi", "802-11-wireless"}
        }

    def status(self) -> dict[str, Any]:
        if shutil.which("nmcli") is None:
            return {
                "ok": False,
                "available": False,
                "wireless_devices": [],
                "message": "小车未安装 NetworkManager（nmcli）",
            }
        try:
            devices = self._wireless_devices()
        except (OSError, subprocess.SubprocessError) as error:
            return {
                "ok": False,
                "available": False,
                "wireless_devices": [],
                "message": f"无法读取小车无线网卡状态：{error}",
            }
        return {
            "ok": True,
            "available": bool(devices),
            "wireless_devices": devices,
            "connection": next(
                (
                    {
                        "ssid": device.get("connection"),
                        "interface": device.get("interface"),
                        "ip_address": device.get("ip_address"),
                        "gateway": device.get("gateway"),
                        "signal": self._number_or_none(device.get("signal")),
                        "connected_since": device.get("connected_since"),
                        "state": device.get("state"),
                    }
                    for device in devices
                    if device.get("state", "").lower() in {"connected", "activated"}
                    and device.get("connection") not in {None, "", "--"}
                ),
                None,
            ),
            "message": "已检测到无线网卡"
            if devices
            else "未检测到可由 NetworkManager 管理的无线网卡",
        }

    @staticmethod
    def _number_or_none(value: object) -> int | None:
        try:
            return int(str(value)) if value not in {None, "", "--"} else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _connection_error_code(message: str) -> str:
        lowered = message.lower()
        if any(word in lowered for word in ("authentication", "password", "secrets", "密码", "密钥")):
            return "authentication_failed"
        if any(word in lowered for word in ("not found", "不可见", "no network", "找不到", "ssid")):
            return "network_unavailable"
        if any(word in lowered for word in ("dhcp", "ip address", "ip4", "gateway", "地址")):
            return "ip_assignment_failed"
        if any(word in lowered for word in ("signal", "weak", "信号", "强度")):
            return "signal_weak"
        if any(word in lowered for word in ("timeout", "timed out", "超时")):
            return "connection_timeout"
        return "connect_failed"

    def _connection_snapshot(self, ssid: str | None = None) -> dict[str, Any]:
        status = self.status()
        connection = status.get("connection")
        if not isinstance(connection, dict) or (
            ssid is not None and connection.get("ssid") != ssid
        ):
            return {
                "connected": False,
                "ssid": ssid,
                "message": "小车当前未连接目标 Wi-Fi",
            }
        if not str(connection.get("ip_address") or "").strip():
            return {
                **connection,
                "connected": False,
                "associated": True,
                "error_code": "ip_assignment_failed",
                "message": "小车已关联目标 Wi-Fi，但未获得 IP 地址",
            }
        signal = connection.get("signal")
        if isinstance(signal, int) and signal < 20:
            connection["warning"] = "signal_weak"
        connection["connected"] = True
        return connection

    def scan(self) -> dict[str, Any]:
        status = self.status()
        if not status["available"]:
            return {**status, "networks": [], "saved_networks": []}
        try:
            result = self._run(
                [
                    "-t",
                    "--escape",
                    "yes",
                    "-f",
                    "SSID,SIGNAL,SECURITY",
                    "device",
                    "wifi",
                    "list",
                    "--rescan",
                    "yes",
                ],
                timeout=20.0,
            )
        except (OSError, subprocess.SubprocessError) as error:
            return {
                "ok": False,
                "networks": [],
                "saved_networks": [],
                "message": f"扫描 Wi-Fi 失败：{error}",
            }
        if result.returncode != 0:
            return {
                "ok": False,
                "networks": [],
                "saved_networks": [],
                "message": f"扫描 Wi-Fi 失败：{self._message(result)}",
            }
        current_ssids = {
            str(device.get("connection", "")).strip()
            for device in status.get("wireless_devices", [])
            if str(device.get("state", "")).lower() in {"connected", "activated"}
            and str(device.get("connection", "")).strip() not in {"", "--"}
        }
        try:
            saved_ssids = self._saved_wifi_profiles()
        except (OSError, subprocess.SubprocessError):
            saved_ssids = set()
        networks: dict[str, dict[str, Any]] = {}
        for line in result.stdout.splitlines():
            values = self._split_terse(line)
            if len(values) < 3 or not values[0]:
                continue
            try:
                signal = max(0, min(100, int(values[1])))
            except ValueError:
                signal = 0
            previous = networks.get(values[0])
            if previous is None or signal > previous["signal"]:
                networks[values[0]] = {
                    "ssid": values[0],
                    "signal": signal,
                    "security": values[2] if values[2] != "--" else "开放网络",
                    "connected": values[0] in current_ssids,
                    "saved": values[0] in saved_ssids,
                    "connectable": True,
                    "connection_state": (
                        "connected" if values[0] in current_ssids else "available"
                    ),
                }
            elif values[0] in current_ssids:
                previous["connected"] = True
                previous["connection_state"] = "connected"
        for network in networks.values():
            network["connectable"] = bool(network["ssid"])
            if network["connected"]:
                network["connection_state"] = "connected"
            elif network["saved"]:
                network["connection_state"] = "saved"
        saved_networks = []
        for ssid in sorted(saved_ssids):
            visible = networks.get(ssid)
            saved_networks.append(
                {
                    "ssid": ssid,
                    "signal": visible["signal"] if visible else None,
                    "security": visible["security"] if visible else "已保存网络",
                    "saved": True,
                    "connected": ssid in current_ssids,
                    "connectable": visible is not None,
                    "connection_state": (
                        "connected" if ssid in current_ssids else "saved"
                    ),
                }
            )
        return {
            "ok": True,
            "networks": sorted(
                networks.values(), key=lambda item: item["signal"], reverse=True
            ),
            "saved_networks": saved_networks,
            "message": "Wi-Fi 扫描完成",
        }

    def connect(self, ssid: str, password: str, hidden: bool) -> dict[str, Any]:
        status = self.status()
        devices = status.get("wireless_devices", [])
        if not status["available"] or not devices:
            return {"ok": False, "message": status["message"], "switching": False}
        arguments = [
            "device",
            "wifi",
            "connect",
            ssid,
            "ifname",
            devices[0]["interface"],
        ]
        if password:
            arguments.extend(["password", password])
        if hidden:
            arguments.extend(["hidden", "yes"])
        try:
            result = self._run(arguments, timeout=35.0)
        except (OSError, subprocess.SubprocessError) as error:
            return {
                "ok": False,
                "message": f"小车连接 Wi-Fi 失败：{error}",
                "switching": False,
            }
        if result.returncode != 0:
            message = self._message(result).replace(password, "***") if password else self._message(result)
            error_code = self._connection_error_code(message)
            return {
                "ok": False,
                "message": f"小车连接 Wi-Fi 失败：{message}",
                "error_code": error_code,
                "switching": False,
            }
        # NetworkManager returns before DHCP and the interface handover finish.
        # Verification is deliberately performed by the follow-up read-only API.
        snapshot = self._connection_snapshot(ssid)
        return {
            "ok": True,
            "message": "小车已保存 Wi-Fi 配置，正在切换网络；当前 App 连接可能会短暂中断。",
            "switching": True,
            "ssid": ssid,
            "connection": snapshot,
        }

    def connect_saved(self, ssid: str) -> dict[str, Any]:
        """Activate a saved NetworkManager profile without receiving a password."""
        if not ssid.strip():
            return {"ok": False, "message": "Wi-Fi 名称不能为空", "switching": False}
        try:
            if ssid not in self._saved_wifi_profiles():
                return {
                    "ok": False,
                    "error_code": "profile_not_found",
                    "message": "小车没有保存该 Wi-Fi，请重新输入密码连接",
                    "switching": False,
                }
            devices = self._wireless_devices()
            interface = devices[0].get("interface") if devices else None
            if not interface:
                return {"ok": False, "message": "小车无线网卡不可用", "switching": False}
            result = self._run(
                ["connection", "up", "id", ssid, "ifname", interface], timeout=35.0
            )
        except (OSError, subprocess.SubprocessError) as error:
            return {"ok": False, "message": f"小车连接已保存 Wi-Fi 失败：{error}", "switching": False}
        if result.returncode != 0:
            message = self._message(result)
            return {
                "ok": False,
                "error_code": self._connection_error_code(message),
                "message": f"小车连接已保存 Wi-Fi 失败：{message}",
                "switching": False,
            }
        snapshot = self._connection_snapshot(ssid)
        return {
            "ok": True,
            "message": "小车正在使用已保存的 Wi-Fi 配置切换网络。",
            "switching": True,
            "ssid": ssid,
            "connection": snapshot,
        }

    def verify(self, ssid: str) -> dict[str, Any]:
        """Read-only confirmation that the rover is connected to the target SSID."""
        snapshot = self._connection_snapshot(ssid)
        if snapshot.get("connected") is not True:
            return {
                "ok": False,
                "verified": False,
                "error_code": "network_not_connected",
                **snapshot,
            }
        if snapshot.get("warning") == "signal_weak":
            return {
                "ok": True,
                "verified": True,
                "error_code": "signal_weak",
                "message": "小车已连接，但 Wi-Fi 信号较弱",
                **snapshot,
            }
        return {"ok": True, "verified": True, "message": "小车已确认连接目标 Wi-Fi", **snapshot}

    def _active_interface_for(self, ssid: str) -> str | None:
        for device in self._wireless_devices():
            if (
                device.get("connection", "").strip() == ssid
                and device.get("state", "").lower() in {"connected", "activated"}
            ):
                return device.get("interface") or None
        return None

    def disconnect(self, ssid: str) -> dict[str, Any]:
        """Disconnect only the active rover connection identified by SSID."""
        if not ssid.strip():
            return {"ok": False, "message": "Wi-Fi 名称不能为空"}
        try:
            interface = self._active_interface_for(ssid)
        except (OSError, subprocess.SubprocessError) as error:
            return {"ok": False, "message": f"无法读取小车 Wi-Fi 状态：{error}"}
        if not interface:
            return {"ok": False, "error_code": "profile_not_active", "message": "该 Wi-Fi 不是小车当前连接的网络"}
        try:
            result = self._run(["device", "disconnect", "ifname", interface])
        except (OSError, subprocess.SubprocessError) as error:
            return {"ok": False, "message": f"断开小车 Wi-Fi 失败：{error}"}
        if result.returncode != 0:
            return {"ok": False, "message": f"断开小车 Wi-Fi 失败：{self._message(result)}"}
        return {"ok": True, "ssid": ssid, "message": "小车已断开该 Wi-Fi"}

    def forget(self, ssid: str) -> dict[str, Any]:
        """Delete only an existing saved Wi-Fi profile on the rover."""
        if not ssid.strip():
            return {"ok": False, "message": "Wi-Fi 名称不能为空"}
        try:
            if ssid not in self._saved_wifi_profiles():
                return {"ok": False, "error_code": "profile_not_found", "message": "小车没有保存该 Wi-Fi"}
            result = self._run(["connection", "delete", "id", ssid])
        except (OSError, subprocess.SubprocessError) as error:
            return {"ok": False, "message": f"删除小车 Wi-Fi 失败：{error}"}
        if result.returncode != 0:
            return {"ok": False, "message": f"删除小车 Wi-Fi 失败：{self._message(result)}"}
        return {"ok": True, "ssid": ssid, "message": "已从小车删除该 Wi-Fi"}


network_manager = NetworkManagerAdapter()
