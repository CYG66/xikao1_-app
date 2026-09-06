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
            devices.append(
                {
                    "interface": values[0],
                    "state": values[2],
                    "connection": values[3],
                }
            )
        return devices

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
            "message": "已检测到无线网卡"
            if devices
            else "未检测到可由 NetworkManager 管理的无线网卡",
        }

    def scan(self) -> dict[str, Any]:
        status = self.status()
        if not status["available"]:
            return {**status, "networks": []}
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
            return {"ok": False, "networks": [], "message": f"扫描 Wi-Fi 失败：{error}"}
        if result.returncode != 0:
            return {
                "ok": False,
                "networks": [],
                "message": f"扫描 Wi-Fi 失败：{self._message(result)}",
            }
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
                }
        return {
            "ok": True,
            "networks": sorted(
                networks.values(), key=lambda item: item["signal"], reverse=True
            ),
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
            return {
                "ok": False,
                "message": f"小车连接 Wi-Fi 失败：{message}",
                "switching": False,
            }
        return {
            "ok": True,
            "message": "小车已保存 Wi-Fi 配置，正在切换网络；当前 App 连接可能会短暂中断。",
            "switching": True,
            "ssid": ssid,
        }


network_manager = NetworkManagerAdapter()
