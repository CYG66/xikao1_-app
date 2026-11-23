#!/usr/bin/env python3
"""Read-only production startup preflight.

This module intentionally imports only the Python standard library.  It must
run before any application module that can create a directory, SQLite database,
table, migration row, JSON store, or append-only audit file.

The preflight never creates, touches, truncates or migrates anything.  It
validates explicit paths, rejects known-unsafe production locations, reports
missing files, and exits non-zero with a machine-readable report when a
blocking condition exists.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

TRUE_VALUES = {"1", "true", "yes", "on"}

PROFILE_ENV = "XLINE_DEPLOYMENT_PROFILE"
PREFLIGHT_OK_ENV = "XLINE_STARTUP_PREFLIGHT_OK"
INTEGRATION_PROFILE_ENV = "XLINE_INTEGRATION_PROFILE"
RECOVERY_MODE_ENV = "XLINE_STARTUP_RECOVERY_MODE"
JSON_IMPORT_ENV = "XLINE_CREATIVE_PROJECT_JSON_IMPORT"
AUTH_MODE_ENV = "XLINE_CONTROL_AUTH_MODE"
AUTH_SECRET_ENV = "XLINE_AUTH_SECRET"
AUTH_TOKEN_ENV = "XLINE_CONTROL_AUTH_TOKEN"
AUTH_ADMIN_TOKEN_ENV = "XLINE_ADMIN_AUTH_TOKEN"
HARDWARE_RUNTIME_ENV = "XLINE_HARDWARE_RUNTIME_ENABLE"
PRINTER_ENV = "XLINE_ENABLE_PRINTER"
PRINTER_AUTHORIZED_ENV = "XLINE_PRINTER_AUTHORIZED"

STATE_ROOT_ENV = "XLINE_STATE_DIR"
CONFIG_ROOT_ENV = "XLINE_CONFIG_DIR"
WORKSPACE_ROOT_ENV = "XLINE_WS_ROOT"

DATABASE_ENV = "XLINE_DATABASE_PATH"
PROJECT_STORE_ENV = "XLINE_CREATIVE_PROJECT_STORE"
TASK_STORE_ENV = "XLINE_AGENT_TASK_STORE"
RUN_STORE_ENV = "XLINE_AGENT_RUN_STORE"
PLAN_STORE_ENV = "XLINE_AGENT_PLAN_STORE"
AUDIT_STORE_ENV = "XLINE_AGENT_AUDIT_STORE"
MEMORY_STORE_ENV = "XLINE_AGENT_MEMORY_STORE"
MISSION_LEDGER_ENV = "XLINE_MISSION_LEDGER_STORE"
DRAWING_VERSION_ENV = "XLINE_DRAWING_VERSION_STORE"
ATTACHMENTS_DIR_ENV = "XLINE_AGENT_ATTACHMENTS_DIR"
PLANNED_RESULTS_DIR_ENV = "XLINE_PLANNED_RESULTS_DIR"
CAD_DIR_ENV = "XLINE_CAD_DIR"
USER_CONFIG_ENV = "XLINE_AGENT_USER_CONFIG_PATH"
MODEL_CONFIG_ENV = "XLINE_AGENT_MODEL_CONFIG_PATH"
AUDIT_HEALTH_STORE_ENV = "XLINE_AGENT_AUDIT_HEALTH_STORE"

# ``required_existing`` is True for stores that are expected to contain the
# existing production history.  Optional stores may be absent on a first
# deployment; their absence is reported as a warning and the preflight still
# does not create them.
PATH_SPECS: tuple[dict[str, Any], ...] = (
    {"env": STATE_ROOT_ENV, "kind": "dir", "root": "state", "required_existing": True},
    {"env": CONFIG_ROOT_ENV, "kind": "dir", "root": "config", "required_existing": True},
    {"env": DATABASE_ENV, "kind": "file", "root": "state", "required_existing": True, "sqlite": True},
    {"env": PROJECT_STORE_ENV, "kind": "file", "root": "state", "required_existing": False},
    {"env": TASK_STORE_ENV, "kind": "file", "root": "state", "required_existing": True},
    {"env": RUN_STORE_ENV, "kind": "file", "root": "state", "required_existing": True},
    {"env": PLAN_STORE_ENV, "kind": "file", "root": "state", "required_existing": True, "sqlite": True},
    {"env": AUDIT_STORE_ENV, "kind": "file", "root": "state", "required_existing": True},
    {"env": MEMORY_STORE_ENV, "kind": "file", "root": "state", "required_existing": False},
    {"env": MEMORY_STORE_ENV, "kind": "file", "root": "state", "required_existing": False},
    {"env": MISSION_LEDGER_ENV, "kind": "file", "root": "state", "required_existing": False},
    {"env": DRAWING_VERSION_ENV, "kind": "file", "root": "state", "required_existing": False},
    {"env": ATTACHMENTS_DIR_ENV, "kind": "dir", "root": "state", "required_existing": False},
    {"env": PLANNED_RESULTS_DIR_ENV, "kind": "dir", "root": "workspace", "required_existing": False},
    {"env": CAD_DIR_ENV, "kind": "dir", "root": "workspace", "required_existing": False},
    {"env": USER_CONFIG_ENV, "kind": "file", "root": "config", "required_existing": False},
    {"env": MODEL_CONFIG_ENV, "kind": "file", "root": "config", "required_existing": False},
)

_ENV_TITLES = {
    DATABASE_ENV: "database",
    PROJECT_STORE_ENV: "creative project store",
    TASK_STORE_ENV: "agent task store",
    RUN_STORE_ENV: "agent run store",
    PLAN_STORE_ENV: "agent plan store",
    AUDIT_STORE_ENV: "agent audit store",
    AUDIT_HEALTH_STORE_ENV: "agent audit health store",
    MEMORY_STORE_ENV: "conversation memory store",
    MISSION_LEDGER_ENV: "mission ledger store",
    DRAWING_VERSION_ENV: "drawing version store",
    ATTACHMENTS_DIR_ENV: "agent attachments",
    PLANNED_RESULTS_DIR_ENV: "planned results",
    CAD_DIR_ENV: "CAD drawing output",
    USER_CONFIG_ENV: "per-user model config",
    MODEL_CONFIG_ENV: "local model config",
}


class PreflightFailure(RuntimeError):
    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        super().__init__("production startup preflight failed")


def _norm(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolve(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _symlink_component_within(root: Path, target: Path) -> Path | None:
    """Return the first symlink between an authorised root and a target path.

    Checking only ``target.is_symlink()`` misses the common bypass where an
    intermediate directory is a link.  The scan is lexical and read-only so it
    can reject a link even when the final directory does not exist yet.
    """
    root_abs = Path(os.path.abspath(str(root.expanduser())))
    target_abs = Path(os.path.abspath(str(target.expanduser())))
    try:
        relative = target_abs.relative_to(root_abs)
    except ValueError:
        return None
    current = root_abs
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return current
    return None


def _truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() in TRUE_VALUES)


def _check_header(path: Path) -> str | None:
    try:
        with path.open("rb") as stream:
            header = stream.read(16)
    except OSError as error:
        return f"无法读取文件头: {error}"
    if not header.startswith(b"SQLite format 3\x00"):
        return "文件不是 SQLite 数据库（缺少 SQLite format 3 文件头）"
    return None


def _stat_type(path: Path) -> str:
    try:
        mode = path.stat().st_mode
    except OSError:
        return "missing"
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "dir"
    if stat.S_ISLNK(mode):
        return "symlink"
    return "other"


def build_report(
    environ: Mapping[str, str] | None = None,
    *,
    profile: str = "production",
    allow_temp_root: bool = False,
) -> dict[str, Any]:
    """Build a read-only preflight report.  Never writes anything."""

    env = os.environ if environ is None else environ
    checks: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    def add(status: str, code: str, env_name: str | None, message: str,
            value: str | None = None) -> None:
        item = {
            "status": status,
            "code": code,
            "env": env_name,
            "message": message,
        }
        if value is not None:
            item["value"] = value
        checks.append(item)
        if status == "FAIL":
            issues.append(item)

    if profile != "production":
        add("FAIL", "PROFILE_UNSUPPORTED", PROFILE_ENV, "仅支持 production profile")
    else:
        add("PASS", "PROFILE", PROFILE_ENV, "profile=production")

    configured_profile = str(env.get(PROFILE_ENV, "")).strip().lower()
    if configured_profile != "production":
        add("FAIL", "DEPLOYMENT_PROFILE", PROFILE_ENV,
            "生产启动必须显式设置 XLINE_DEPLOYMENT_PROFILE=production")
    else:
        add("PASS", "DEPLOYMENT_PROFILE", PROFILE_ENV,
            "XLINE_DEPLOYMENT_PROFILE=production")

    if _truthy(env.get(INTEGRATION_PROFILE_ENV)):
        add("FAIL", "INTEGRATION_PROFILE", INTEGRATION_PROFILE_ENV,
            "生产启动不得启用 integration profile")
    else:
        add("PASS", "INTEGRATION_PROFILE", INTEGRATION_PROFILE_ENV,
            "integration profile 未启用")

    runtime_profile = str(env.get("XLINE_RUNTIME_PROFILE", "")).strip().lower()
    if not runtime_profile:
        add("FAIL", "RUNTIME_PROFILE", "XLINE_RUNTIME_PROFILE",
            "生产启动必须显式设置 XLINE_RUNTIME_PROFILE")
    elif runtime_profile == "virtual_sim":
        add("FAIL", "RUNTIME_PROFILE", "XLINE_RUNTIME_PROFILE",
            "生产启动不得使用 virtual_sim")
    else:
        add("PASS", "RUNTIME_PROFILE", "XLINE_RUNTIME_PROFILE",
            f"XLINE_RUNTIME_PROFILE={runtime_profile}")

    recovery_mode = str(env.get(RECOVERY_MODE_ENV, "")).strip().lower()
    if recovery_mode not in {"disabled", "authorized"}:
        add("FAIL", "RECOVERY_MODE", RECOVERY_MODE_ENV,
            "必须显式设置 XLINE_STARTUP_RECOVERY_MODE=disabled|authorized")
    elif recovery_mode == "authorized":
        add("WARN", "RECOVERY_MODE", RECOVERY_MODE_ENV,
            "已授权启动恢复：将重写未完成任务状态，需在审计中保留依据")
    else:
        add("PASS", "RECOVERY_MODE", RECOVERY_MODE_ENV,
            "启动恢复已禁用（只读启动）")

    json_import = str(env.get(JSON_IMPORT_ENV, "")).strip().lower()
    if json_import != "disabled":
        add("FAIL", "JSON_IMPORT", JSON_IMPORT_ENV,
            "生产启动不得启用历史 JSON 自动回退；必须显式设为 disabled")
    else:
        add("PASS", "JSON_IMPORT", JSON_IMPORT_ENV,
            "历史 JSON 自动回退已禁用")

    auth_mode = str(env.get(AUTH_MODE_ENV, "")).strip().lower()
    if profile == "production" and auth_mode != "enforced":
        add("FAIL", "AUTH_MODE", AUTH_MODE_ENV,
            "生产启动必须显式设置 XLINE_CONTROL_AUTH_MODE=enforced")
    else:
        add("PASS", "AUTH_MODE", AUTH_MODE_ENV, f"auth_mode={auth_mode or 'disabled'}")
    auth_secret = str(env.get(AUTH_SECRET_ENV, "")).strip()
    if profile == "production" and len(auth_secret) < 32:
        add("FAIL", "AUTH_SECRET", AUTH_SECRET_ENV,
            "生产启动要求 XLINE_AUTH_SECRET 至少 32 字符")
    elif auth_secret:
        add("PASS", "AUTH_SECRET", AUTH_SECRET_ENV, "认证密钥已配置")
    tokens = [
        str(env.get(AUTH_TOKEN_ENV, "")).strip(),
        str(env.get(AUTH_ADMIN_TOKEN_ENV, "")).strip(),
    ]
    if profile == "production" and not any(tokens):
        add("FAIL", "AUTH_TOKEN", AUTH_TOKEN_ENV,
            "生产启动要求至少一个签名控制令牌")
    else:
        add("PASS", "AUTH_TOKEN", AUTH_TOKEN_ENV, "控制令牌已配置" if any(tokens) else "未配置控制令牌")
    if profile == "production" and not str(env.get(AUTH_ADMIN_TOKEN_ENV, "")).strip():
        add("WARN", "AUTH_ADMIN_TOKEN", AUTH_ADMIN_TOKEN_ENV,
            "未配置管理员令牌：数据库和 Wi-Fi 管理接口将无人可用")

    hardware_runtime = _truthy(env.get(HARDWARE_RUNTIME_ENV))
    printer_requested = _truthy(env.get(PRINTER_ENV))
    printer_authorized = _truthy(env.get(PRINTER_AUTHORIZED_ENV))
    if printer_requested and not printer_authorized:
        add("FAIL", "PRINTER_AUTHORIZED", PRINTER_AUTHORIZED_ENV,
            "XLINE_ENABLE_PRINTER=true 时必须显式设置 XLINE_PRINTER_AUTHORIZED=1")
    elif printer_requested:
        add("PASS", "PRINTER_AUTHORIZED", PRINTER_AUTHORIZED_ENV, "喷墨已显式授权")
    else:
        add("PASS", "PRINTER_DEFAULT_OFF", PRINTER_ENV, "喷墨默认关闭")
    add("PASS", "HARDWARE_RUNTIME",
        HARDWARE_RUNTIME_ENV,
        "硬件 runtime 显式启用" if hardware_runtime else "硬件 runtime 默认关闭，需显式授权")

    root_values: dict[str, Path | None] = {"state": None, "config": None, "workspace": None}
    raw_root_values: dict[str, Path] = {}
    root_symlinks: dict[str, bool] = {}
    raw_state = str(env.get(STATE_ROOT_ENV, "")).strip()
    raw_config = str(env.get(CONFIG_ROOT_ENV, "")).strip()
    raw_workspace = str(env.get(WORKSPACE_ROOT_ENV, "")).strip()
    for key, raw in (("state", raw_state), ("config", raw_config),
                     ("workspace", raw_workspace)):
        if raw and Path(raw).expanduser().is_absolute():
            raw_root_values[key] = Path(raw).expanduser()
        if raw and Path(raw).expanduser().is_symlink():
            root_symlinks[key] = True
            add("FAIL", f"ROOT_SYMLINK_{key.upper()}", None,
                f"{key} 根目录不得是符号链接: {raw}")
    if not raw_state:
        add("FAIL", "MISSING_ROOT", STATE_ROOT_ENV, "缺少显式生产状态目录")
    elif not Path(raw_state).expanduser().is_absolute():
        add("FAIL", "ROOT_NOT_ABSOLUTE_STATE", STATE_ROOT_ENV,
            f"state 根目录不是绝对路径: {raw_state}")
    else:
        root_values["state"] = _resolve(Path(raw_state))
    if not raw_config:
        add("FAIL", "MISSING_ROOT", CONFIG_ROOT_ENV, "缺少显式生产配置目录")
    elif not Path(raw_config).expanduser().is_absolute():
        add("FAIL", "ROOT_NOT_ABSOLUTE_CONFIG", CONFIG_ROOT_ENV,
            f"config 根目录不是绝对路径: {raw_config}")
    else:
        root_values["config"] = _resolve(Path(raw_config))
    if raw_workspace:
        if not Path(raw_workspace).expanduser().is_absolute():
            add("FAIL", "ROOT_NOT_ABSOLUTE_WORKSPACE", WORKSPACE_ROOT_ENV,
                f"workspace 根目录不是绝对路径: {raw_workspace}")
        else:
            root_values["workspace"] = _resolve(Path(raw_workspace))

    for key, root in root_values.items():
        if root is None or root_symlinks.get(key):
            continue
        if not root.is_absolute():
            add("FAIL", f"ROOT_NOT_ABSOLUTE_{key.upper()}", None,
                f"{key} 根目录不是绝对路径: {root}")
            continue
        if not root.exists() or not root.is_dir():
            add("FAIL", f"ROOT_MISSING_{key.upper()}", None,
                f"{key} 根目录不存在或不是目录: {root}")
            continue
        if not os.access(root, os.W_OK):
            add("FAIL", f"ROOT_NOT_WRITABLE_{key.upper()}", None,
                f"{key} 根目录不可写: {root}")
            continue
        add("PASS", f"ROOT_{key.upper()}", None, f"{key} 根目录可用")

    if not allow_temp_root and root_values["state"] is not None:
        temp_root = _resolve(Path(tempfile.gettempdir()))
        if _is_relative_to(root_values["state"], temp_root):
            add("FAIL", "STATE_ROOT_TEMP", STATE_ROOT_ENV,
                "生产状态目录不得位于系统临时目录")

    resolved: dict[str, str] = {}
    file_paths: dict[str, Path] = {}
    for spec in PATH_SPECS:
        env_name = str(spec["env"])
        kind = str(spec["kind"])
        root_name = str(spec["root"])
        required = bool(spec["required_existing"])
        raw = str(env.get(env_name, "")).strip()
        if not raw:
            add("FAIL", f"MISSING_{env_name}", env_name,
                f"缺少必填生产路径: {env_name}")
            continue
        raw_path = Path(raw).expanduser()
        if not raw_path.is_absolute():
            add("FAIL", f"NOT_ABSOLUTE_{env_name}", env_name,
                f"路径不是绝对路径: {raw}")
            continue
        if raw_path.is_symlink():
            add("FAIL", f"SYMLINK_{env_name}", env_name,
                f"生产路径不得是符号链接: {raw_path}")
            continue
        raw_root = raw_root_values.get(root_name)
        if raw_root is not None:
            linked = _symlink_component_within(raw_root, raw_path)
            if linked is not None:
                add("FAIL", f"SYMLINK_COMPONENT_{env_name}", env_name,
                    f"生产路径的上级目录包含符号链接: {linked}")
                continue
        path = _resolve(raw_path)
        resolved[env_name] = str(path)
        root = root_values.get(root_name)
        if root is None:
            add("FAIL", f"ROOT_UNAVAILABLE_{env_name}", env_name,
                f"{env_name} 缺少可验证的 {root_name} 根目录")
            continue
        if root_name == "workspace" and (not raw_workspace):
            add("FAIL", f"WORKSPACE_ROOT_{env_name}", WORKSPACE_ROOT_ENV,
                f"{env_name} 需要显式 XLINE_WS_ROOT 才能验证")
            continue
        if not _is_relative_to(path, root):
            add("FAIL", f"OUTSIDE_ROOT_{env_name}", env_name,
                f"路径不在允许的 {root_name} 根目录内: {path}")
            continue

        actual = _stat_type(path)
        if kind == "dir":
            if actual == "missing":
                if required:
                    add("FAIL", f"MISSING_{env_name}", env_name,
                        f"必填目录不存在: {path}")
                else:
                    add("WARN", f"ABSENT_{env_name}", env_name,
                        f"目录尚不存在，首次写入时才会创建: {path}")
                continue
            if actual != "dir":
                add("FAIL", f"TYPE_{env_name}", env_name,
                    f"路径存在但不是目录: {path}")
                continue
            if not os.access(path, os.R_OK):
                add("FAIL", f"UNREADABLE_{env_name}", env_name,
                    f"目录不可读: {path}")
                continue
            add("PASS", f"DIR_{env_name}", env_name, f"目录可用: {path}")
            continue

        if actual == "missing":
            if required:
                add("FAIL", f"MISSING_{env_name}", env_name,
                    f"必填文件不存在: {path}")
                continue
            parent = path.parent
            if not parent.exists() or not parent.is_dir():
                add("FAIL", f"PARENT_{env_name}", env_name,
                    f"父目录不存在: {parent}")
                continue
            if not os.access(parent, os.W_OK):
                add("FAIL", f"PARENT_NOT_WRITABLE_{env_name}", env_name,
                    f"父目录不可写: {parent}")
                continue
            add("WARN", f"ABSENT_{env_name}", env_name,
                f"文件尚不存在，首次写入时才会创建: {path}")
            continue
        if actual != "file":
            add("FAIL", f"TYPE_{env_name}", env_name,
                f"路径存在但不是普通文件: {path}")
            continue
        if not os.access(path, os.R_OK):
            add("FAIL", f"UNREADABLE_{env_name}", env_name,
                f"文件不可读: {path}")
            continue
        if not os.access(path, os.W_OK):
            add("FAIL", f"NOT_WRITABLE_{env_name}", env_name,
                f"文件不可写: {path}")
            continue
        if spec.get("sqlite"):
            header_error = _check_header(path)
            if header_error:
                add("FAIL", f"SQLITE_HEADER_{env_name}", env_name,
                    f"{path}: {header_error}")
                continue
        file_paths[env_name] = path
        add("PASS", f"FILE_{env_name}", env_name, f"文件可用: {path}",
            _ENV_TITLES.get(env_name))

    # Duplicate paths would make two logical stores share one file.
    duplicates = sorted(
        path for path, count in _counts(file_paths.values()).items() if count > 1
    )
    for duplicated in duplicates:
        add("FAIL", "DUPLICATE_PATH", None,
            f"多个存储指向同一路径: {duplicated}")

    report = {
        "ok": not issues,
        "profile": profile,
        "read_only": True,
        "policy": {
            "deployment_profile": configured_profile,
            "integration_profile": _truthy(env.get(INTEGRATION_PROFILE_ENV)),
            "runtime_profile": runtime_profile,
            "recovery_mode": recovery_mode,
            "json_import": json_import,
            "auth_mode": auth_mode,
            "hardware_runtime_enabled": hardware_runtime,
            "printer_requested": printer_requested,
            "printer_authorized": printer_authorized,
        },
        "resolved_paths": resolved,
        "checks": checks,
        "warnings": [item for item in checks if item["status"] == "WARN"],
        "issues": issues,
    }
    return report


def _counts(paths) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in paths:
        key = _norm(path)
        counts[key] = counts.get(key, 0) + 1
    return counts


def validate_preflight(
    environ: Mapping[str, str] | None = None,
    *,
    profile: str = "production",
    allow_temp_root: bool = False,
) -> dict[str, Any]:
    report = build_report(
        environ, profile=profile, allow_temp_root=allow_temp_root
    )
    if not report["ok"]:
        raise PreflightFailure(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="production", choices=["production"])
    parser.add_argument("--json", action="store_true", help="emit the full JSON report")
    args = parser.parse_args(argv)
    try:
        report = validate_preflight(os.environ, profile=args.profile)
    except PreflightFailure as failure:
        report = failure.report
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            "startup preflight PASS: "
            f"{len(report['checks'])} checks, {len(report['warnings'])} warnings"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
