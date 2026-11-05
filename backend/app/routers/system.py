from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from ..agent_service import robot_agent
from ..database import xline_database
from ..discovery import rover_discovery
from ..network_manager import network_manager
from ..ros_adapter import ros_adapter
from ..schemas import DatabaseCleanupRequest, WifiNetworkCommand, WifiProvisionRequest
from ..state import robot_state
from ..telemetry_contract import (
    build_mission_contract,
    build_printer_contract,
    build_status_packet,
    build_telemetry_contract,
)


router = APIRouter()


@router.get("/health")
def health() -> dict[str, object]:
    return {
        "ok": True,
        "device_id": rover_discovery.device_id,
        "discovery": rover_discovery.payload(),
        "status": build_status_packet(robot_state.snapshot()),
    }


@router.get("/api/status")
def status() -> dict[str, object]:
    robot_agent.reconcile_verification_tasks()
    snapshot = robot_state.snapshot()
    xline_database.record_telemetry(snapshot)
    xline_database.upsert_device_capabilities(snapshot, ros_adapter.interface_snapshot())
    return build_status_packet(snapshot)


@router.get("/api/telemetry")
def telemetry_contract() -> dict[str, object]:
    """Return the stable live telemetry contract used by the App monitor."""
    robot_agent.reconcile_verification_tasks()
    snapshot = robot_state.snapshot()
    xline_database.record_telemetry(snapshot)
    return {
        "ok": True,
        "telemetry": build_telemetry_contract(snapshot),
        "printer": build_printer_contract(snapshot),
        "mission": build_mission_contract(snapshot),
    }


@router.get("/api/telemetry/history")
def telemetry_history(minutes: int = 120, limit: int = 600) -> dict[str, object]:
    """Return persisted, downsampled monitoring data; never drives hardware."""
    range_minutes = max(2, min(minutes, 7 * 24 * 60))
    maximum = max(10, min(limit, 2000))
    return {
        "ok": True,
        "range_minutes": range_minutes,
        "samples": xline_database.telemetry_history(range_minutes, maximum),
    }


@router.get("/api/network/status")
def network_status() -> dict[str, object]:
    """Read-only rover Wi-Fi adapter status; credentials are never exposed."""
    return network_manager.status()


@router.get("/api/network/wifi")
def network_scan() -> dict[str, object]:
    """List visible SSIDs from the rover's NetworkManager-owned adapter."""
    return network_manager.scan()


@router.post("/api/network/wifi")
def network_connect(command: WifiProvisionRequest) -> dict[str, object]:
    """Persist a Wi-Fi connection through NetworkManager without logging secrets."""
    return network_manager.connect(command.ssid, command.password, command.hidden)


@router.post("/api/network/wifi/connect-saved")
def network_connect_saved(command: WifiNetworkCommand) -> dict[str, object]:
    """Activate a saved rover Wi-Fi profile without sending a password."""
    return network_manager.connect_saved(command.ssid)


@router.get("/api/network/wifi/verify")
def network_verify(ssid: str) -> dict[str, object]:
    """Read-only verification of the rover's active Wi-Fi connection."""
    return network_manager.verify(ssid)


@router.post("/api/network/wifi/disconnect")
def network_wifi_disconnect(command: WifiNetworkCommand) -> dict[str, object]:
    """Disconnect only the rover's active Wi-Fi interface."""
    return network_manager.disconnect(command.ssid)


@router.post("/api/network/wifi/forget")
def network_wifi_forget(command: WifiNetworkCommand) -> dict[str, object]:
    """Forget a saved rover Wi-Fi profile without exposing credentials."""
    return network_manager.forget(command.ssid)


@router.get("/api/database/summary")
def database_summary() -> dict[str, object]:
    """Return persistence health; this never participates in safety decisions."""
    return xline_database.summary()


@router.get("/api/database/migrations")
def database_migrations() -> dict[str, object]:
    return {"ok": True, **xline_database.migration_status()}


@router.post("/api/database/backup")
def database_backup() -> dict[str, object]:
    """Create a timestamped backup beside the configured database."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destination = xline_database.path.with_name(
        f"{xline_database.path.stem}.{stamp}.backup.sqlite"
    )
    return xline_database.backup(destination)


@router.get("/api/database/integrity")
def database_integrity() -> dict[str, object]:
    """Run a read-only database integrity and storage check."""
    return xline_database.integrity_status()


@router.post("/api/database/cleanup")
def database_cleanup(command: DatabaseCleanupRequest) -> dict[str, object]:
    """Clean bounded history only; projects and mission records are preserved."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_destination = xline_database.path.with_name(
        f"{xline_database.path.stem}.pre-cleanup.{stamp}.backup.sqlite"
    )
    backup = xline_database.backup(backup_destination)
    result = xline_database.cleanup_history(command.retention_days, command.targets)
    result["backup"] = backup
    result["integrity"] = xline_database.integrity_status()
    return result


from ..state import robot_state

@router.get("/api/logs")
def logs() -> dict[str, list[str]]:
    return {"logs": robot_state.logs}

