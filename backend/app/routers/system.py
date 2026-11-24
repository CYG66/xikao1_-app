from __future__ import annotations

from fastapi import APIRouter

from ..agent_service import robot_agent
from ..audit_store import agent_audit
from ..backup_manager import backup_manager
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
    audit_health = agent_audit.health_status()
    return {
        "ok": True,
        "device_id": rover_discovery.device_id,
        "discovery": rover_discovery.payload(),
        "status": build_status_packet(robot_state.snapshot()),
        "audit": audit_health,
        "audit_degraded": bool(audit_health.get("degraded")),
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
    """Create a verified backup of the database and all persistent stores."""
    return backup_manager.create_backup(database=xline_database, audit=agent_audit)


@router.post("/api/database/backup/verify")
def database_backup_verify(backup_dir: str) -> dict[str, object]:
    from ..backup_manager import verify_backup

    return verify_backup(backup_dir)


@router.post("/api/database/restore")
def database_restore(
    backup_dir: str,
    target_root: str,
    dry_run: bool = True,
    force: bool = False,
    confirm: str = "",
) -> dict[str, object]:
    from ..backup_manager import restore_backup

    if not dry_run and confirm != "RESTORE-ISOLATED":
        return {"ok": False, "error": "restore requires confirm=RESTORE-ISOLATED"}
    return restore_backup(backup_dir, target_root, dry_run=dry_run, force=force)


@router.get("/api/database/integrity")
def database_integrity() -> dict[str, object]:
    """Run a read-only database integrity and storage check."""
    return xline_database.integrity_status()


@router.post("/api/database/cleanup")
def database_cleanup(command: DatabaseCleanupRequest) -> dict[str, object]:
    """Clean bounded history only; projects and mission records are preserved."""
    backup = backup_manager.create_backup(
        prefix="pre-cleanup", database=xline_database, audit=agent_audit
    )
    result = xline_database.cleanup_history(command.retention_days, command.targets)
    result["backup"] = backup
    result["integrity"] = xline_database.integrity_status()
    return result


from ..state import robot_state

@router.get("/api/logs")
def logs() -> dict[str, list[str]]:
    return {"logs": robot_state.logs}

