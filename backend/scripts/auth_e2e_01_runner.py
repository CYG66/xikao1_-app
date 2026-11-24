"""RELEASE-AUTH-E2E-01 offline runner.

Starts the real FastAPI application in virtual simulation mode, issues signed
tokens offline, drives the App's `AuthTransport` through HTTP + WebSocket, then
restarts the single worker with a rotated secret to prove service-wide
revocation.  No real robot, printer, model or production database is touched.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
PYTHON = Path(sys.executable)
DART = Path(r"C:\Users\29924\Softwares\flutter\bin\dart.bat")

sys.path.insert(0, str(BACKEND))
from app.security import decode_token, issue_token  # noqa: E402

SECRET_1 = secrets.token_urlsafe(48)
SECRET_2 = secrets.token_urlsafe(48)
TTL = 3600


def _paths(root: Path) -> dict[str, str]:
    return {
        "XLINE_DATABASE_PATH": str(root / "state" / "xline.db"),
        "XLINE_CREATIVE_PROJECT_STORE": str(root / "state" / "creative_projects.json"),
        "XLINE_AGENT_TASK_STORE": str(root / "state" / "tasks.json"),
        "XLINE_AGENT_RUN_STORE": str(root / "state" / "agent_runs.json"),
        "XLINE_AGENT_PLAN_STORE": str(root / "state" / "agent_plans.sqlite3"),
        "XLINE_AGENT_AUDIT_STORE": str(root / "state" / "agent_audit.jsonl"),
        "XLINE_AGENT_AUDIT_HEALTH_STORE": str(root / "state" / "agent_audit_health.json"),
        "XLINE_AGENT_MEMORY_STORE": str(root / "state" / "conversation_memory.json"),
        "XLINE_MISSION_LEDGER_STORE": str(root / "state" / "mission_ledger.json"),
        "XLINE_DRAWING_VERSION_STORE": str(root / "state" / "drawing_versions.json"),
        "XLINE_AGENT_ATTACHMENTS_DIR": str(root / "state" / "attachments"),
        "XLINE_PLANNED_RESULTS_DIR": str(root / "workspace" / "planned_results"),
        "XLINE_CAD_DIR": str(root / "workspace" / "cad"),
        "XLINE_AGENT_USER_CONFIG_PATH": str(root / "config" / "xline-agent-users.json"),
        "XLINE_AGENT_MODEL_CONFIG_PATH": str(root / "config" / "xline-agent.json"),
        "XLINE_BACKUP_ROOT": str(root / "state" / "backups"),
        "XLINE_RESTORE_ROOT": str(root / "restore"),
    }


def _write_token(path: Path, token: str) -> None:
    path.write_text(token + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_ready(url: str, token: str, process: subprocess.Popen[str], timeout: float = 35.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            return False
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, ConnectionError, urllib.error.HTTPError):
            pass
        time.sleep(0.4)
    return False


def _make_env(root: Path, secret: str, control_token: str, admin_token: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(_paths(root))
    env.update({
        "PYTHONPATH": str(BACKEND),
        "XLINE_DEPLOYMENT_PROFILE": "test",
        "XLINE_CONTROL_AUTH_MODE": "enforced",
        "XLINE_AUTH_SECRET": secret,
        "XLINE_CONTROL_AUTH_TOKEN": control_token,
        "XLINE_ADMIN_AUTH_TOKEN": admin_token,
        "XLINE_RUNTIME_PROFILE": "virtual_sim",
        "XLINE_EMBEDDED_DISCOVERY": "0",
        "XLINE_HARDWARE_RUNTIME_ENABLE": "0",
        "XLINE_PRINTER_AUTHORIZED": "0",
        "XLINE_ENABLE_PRINTER": "0",
        "XLINE_CREATIVE_PROJECT_JSON_IMPORT": "disabled",
        "XLINE_STARTUP_RECOVERY_MODE": "disabled",
        "XLINE_CORS_ORIGINS": "*",
    })
    return env


def _start_server(root: Path, secret: str, control: str, admin: str, port: int) -> subprocess.Popen[str]:
    log_path = root / f"uvicorn-{port}.log"
    log = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            str(PYTHON), "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1", "--port", str(port),
            "--workers", "1", "--log-level", "info",
        ],
        cwd=str(BACKEND),
        env=_make_env(root, secret, control, admin),
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return process


def _stop_server(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="xline-auth-e2e-"))
    evidence: dict[str, object] = {"root": str(root), "cases": [], "server_logs": []}

    valid = issue_token("app-operator", secret=SECRET_1, role="operator", ttl_seconds=TTL)
    admin = issue_token("app-admin", secret=SECRET_1, role="admin", ttl_seconds=TTL)
    readonly = issue_token("app-readonly", secret=SECRET_1, role="readonly", ttl_seconds=TTL)
    expired = issue_token("app-expired", secret=SECRET_1, role="operator", ttl_seconds=1, now=1)
    forged = issue_token("app-forged", secret=SECRET_2, role="operator", ttl_seconds=TTL)
    tokens = {
        "valid": root / "valid.token",
        "admin": root / "admin.token",
        "readonly": root / "readonly.token",
        "expired": root / "expired.token",
        "expiry": root / "expiry.token",
        "forged": root / "forged.token",
    }
    for name, value in {
        "valid": valid, "admin": admin, "readonly": readonly,
        "expired": expired, "forged": forged,
    }.items():
        _write_token(tokens[name], value)

    # Compile once so the expiry token can be issued immediately before the
    # session test; a cold `dart run` compile would consume its short TTL.
    executable = root / "auth_e2e_client.exe"
    compile_result = subprocess.run(
        [str(DART), "compile", "exe", "tool/auth_e2e_client.dart", "-o", str(executable)],
        cwd=str(ROOT), text=True, capture_output=True, timeout=180,
    )
    evidence["dart_compile_exit"] = compile_result.returncode
    evidence["dart_compile_stderr"] = compile_result.stderr[-2000:]
    client_command = [str(executable)] if compile_result.returncode == 0 else [str(DART), "run", "tool/auth_e2e_client.dart"]

    port = _free_port()
    process = _start_server(root, SECRET_1, valid, admin, port)
    base = f"http://127.0.0.1:{port}"
    try:
        ready = _wait_ready(f"{base}/api/status", valid, process)
        evidence["server_ready"] = ready
        if not ready:
            evidence["error"] = "server did not become ready"
            print(json.dumps(evidence, ensure_ascii=False))
            return 2

        command = [
            *client_command,
            "--base", base,
            "--valid", str(tokens["valid"]),
            "--readonly", str(tokens["readonly"]),
            "--expired", str(tokens["expired"]),
            "--expiry", str(tokens["expiry"]),
            "--forged", str(tokens["forged"]),
        ]
        expiry = issue_token("app-expiry", secret=SECRET_1, role="operator", ttl_seconds=10)
        _write_token(tokens["expiry"], expiry)
        try:
            expiry_principal = decode_token(expiry, secret=SECRET_1)
            evidence["expiry_metadata"] = {
                "subject": expiry_principal.subject,
                "role": expiry_principal.role,
                "scopes": sorted(expiry_principal.scopes),
                "expires_in": expiry_principal.expires_at - int(time.time()),
            }
        except Exception as error:  # pragma: no cover - diagnostic only
            evidence["expiry_metadata"] = {"decode_error": str(error)}
        result = subprocess.run(
            command, cwd=str(ROOT), text=True, capture_output=True, timeout=120,
        )
        cases = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
        evidence["cases"] = cases
        evidence["dart_exit"] = result.returncode
        evidence["dart_stderr"] = result.stderr[-4000:]
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        if result.returncode != 0 or any(not item.get("ok") for item in cases):
            return 1
    finally:
        _stop_server(process)
        evidence["server_logs"].append(str(root / f"uvicorn-{port}.log"))

    # Service-wide revocation: rotate the signing secret and restart the single
    # worker.  The old token is no longer accepted, even though its payload is
    # otherwise well-formed and unexpired.
    new_valid = issue_token("app-operator-rotated", secret=SECRET_2, role="operator", ttl_seconds=TTL)
    new_admin = issue_token("app-admin-rotated", secret=SECRET_2, role="admin", ttl_seconds=TTL)
    port2 = _free_port()
    process2 = _start_server(root, SECRET_2, new_valid, new_admin, port2)
    base2 = f"http://127.0.0.1:{port2}"
    revocation: dict[str, object]
    try:
        ready = _wait_ready(f"{base2}/api/status", new_valid, process2)
        revocation = {"server_ready": ready}
        if not ready:
            revocation["ok"] = False
            revocation["error"] = "rotated server did not become ready"
        else:
            command = [
                *client_command,
                "--mode", "status",
                "--base", base2,
                "--valid", str(tokens["valid"]),
            ]
            result = subprocess.run(
                command, cwd=str(ROOT), text=True, capture_output=True, timeout=45,
            )
            cases = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
            revocation["cases"] = cases
            revocation["dart_exit"] = result.returncode
            revocation["dart_stderr"] = result.stderr[-2000:]
            revocation["ok"] = result.returncode == 0 and all(item.get("ok") for item in cases)
    finally:
        _stop_server(process2)
        evidence["server_logs"].append(str(root / f"uvicorn-{port2}.log"))

    evidence["revocation"] = revocation
    payload = json.dumps(evidence, ensure_ascii=False, indent=2)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8")
    print(payload)
    return 0 if revocation.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
