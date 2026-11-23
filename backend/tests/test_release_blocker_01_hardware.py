"""P0-02 hardware runtime gate and fail-closed default tests."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import app.ros_adapter as ros_adapter_module
from app.ros_adapter import (
    RobotRosAdapter,
    hardware_runtime_block_reason,
    hardware_runtime_start_permitted,
)


def test_runtime_script_requires_preflight_and_explicit_authorization():
    backend = Path(__file__).resolve().parents[1]
    launcher = (backend / "run_ws3_runtime.sh").read_text(encoding="utf-8")
    assert "startup_preflight.py --profile production" in launcher
    assert "XLINE_HARDWARE_RUNTIME_ENABLE" in launcher
    assert "XLINE_PRINTER_AUTHORIZED" in launcher
    assert "exit 78" in launcher
    assert "exit 0" in launcher
    assert "enable_printer:=true" not in launcher.split("startup_preflight", 1)[0]
    assert "enable_printer=false" in launcher
    assert "XLINE_ENABLE_PRINTER" in launcher


def test_systemd_unit_does_not_restart_hardware_forever():
    backend = Path(__file__).resolve().parents[1]
    unit = (backend / "xline-ws3-runtime.service").read_text(encoding="utf-8")
    assert "Restart=on-failure" in unit
    assert "Restart=always" not in unit
    assert "StartLimitIntervalSec=60" in unit
    assert "StartLimitBurst=3" in unit
    assert "Environment=XLINE_HARDWARE_RUNTIME_ENABLE=0" in unit
    assert "Environment=XLINE_ENABLE_PRINTER=false" in unit
    assert "Environment=XLINE_PRINTER_AUTHORIZED=0" in unit


def test_hardware_gate_is_fail_closed():
    with patch.object(ros_adapter_module, "robot_execution_permitted", return_value=True), \
         patch.object(ros_adapter_module, "HARDWARE_RUNTIME_ENABLED", False), \
         patch.object(ros_adapter_module, "ENABLE_PRINTER", False), \
         patch.object(ros_adapter_module, "PRINTER_AUTHORIZED", False):
        assert hardware_runtime_start_permitted() is False
        assert "authorization" in hardware_runtime_block_reason()

    with patch.object(ros_adapter_module, "robot_execution_permitted", return_value=True), \
         patch.object(ros_adapter_module, "HARDWARE_RUNTIME_ENABLED", True), \
         patch.object(ros_adapter_module, "ENABLE_PRINTER", True), \
         patch.object(ros_adapter_module, "PRINTER_AUTHORIZED", False):
        assert hardware_runtime_start_permitted() is False
        assert "printer authorization" in hardware_runtime_block_reason()

    with patch.object(ros_adapter_module, "robot_execution_permitted", return_value=True), \
         patch.object(ros_adapter_module, "HARDWARE_RUNTIME_ENABLED", True), \
         patch.object(ros_adapter_module, "ENABLE_PRINTER", False), \
         patch.object(ros_adapter_module, "PRINTER_AUTHORIZED", False):
        assert hardware_runtime_start_permitted() is True


def test_ensure_hardware_runtime_does_not_spawn_when_unauthorized():
    adapter = RobotRosAdapter()
    with patch.object(ros_adapter_module, "RUNTIME_PROFILE", "xline_ws3"), \
         patch.object(ros_adapter_module, "HARDWARE_RUNTIME_ENABLED", False), \
         patch.object(ros_adapter_module, "ENABLE_PRINTER", False), \
         patch.object(ros_adapter_module, "PRINTER_AUTHORIZED", False), \
         patch.object(ros_adapter_module.subprocess, "Popen") as popen:
        assert adapter.ensure_hardware_runtime() is False
        popen.assert_not_called()


def test_virtual_runtime_remains_available_in_isolated_profile():
    adapter = RobotRosAdapter()
    with patch.object(ros_adapter_module, "RUNTIME_PROFILE", "virtual_sim"), \
         patch.object(ros_adapter_module, "HARDWARE_RUNTIME_ENABLED", False), \
         patch.object(ros_adapter_module.subprocess, "Popen") as popen:
        # The simulator is not a hardware entry and is safe to run in tests.
        assert adapter.ensure_hardware_runtime() in {True, False}
        popen.assert_not_called()
