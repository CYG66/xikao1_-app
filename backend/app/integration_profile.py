"""Fail-closed admission for the Integration-03 verification profile.

The profile is opt-in.  When enabled, it validates all storage paths before
application submodules are imported, forces offline/virtual runtime switches,
and exposes two narrow runtime predicates used by the model gateway and robot
adapter.  Ordinary production startup is unchanged because the profile is off
unless ``XLINE_INTEGRATION_PROFILE`` is truthy.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Mapping, MutableMapping


PROFILE_ENV = "XLINE_INTEGRATION_PROFILE"
ISOLATION_ROOT_ENV = "XLINE_INTEGRATION_ISOLATION_ROOT"
DATABASE_PATH_ENV = "XLINE_DATABASE_PATH"
PROJECT_STORE_ENV = "XLINE_CREATIVE_PROJECT_STORE"
PRODUCTION_DATABASE_ENV = "XLINE_PRODUCTION_DATABASE_PATH"
PRODUCTION_PROJECT_STORE_ENV = "XLINE_PRODUCTION_CREATIVE_PROJECT_STORE"

REQUIRED_PATH_ENVS = (
    ISOLATION_ROOT_ENV,
    DATABASE_PATH_ENV,
    PROJECT_STORE_ENV,
    PRODUCTION_DATABASE_ENV,
)

_TRUE_VALUES = {"1", "true", "yes", "on"}


class IntegrationProfileError(RuntimeError):
    """Raised when the integration verification profile is unsafe to start."""


def _flag_value(value: str | None) -> bool:
    return bool(value and value.strip().lower() in _TRUE_VALUES)


def integration_profile_enabled(environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return _flag_value(env.get(PROFILE_ENV))


def _platform_state_root() -> Path:
    if os.name == "nt":
        return Path(tempfile.gettempdir()) / "xline-agent"
    return Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "xline-agent"


def known_production_database_path() -> Path:
    return _platform_state_root() / "xline.db"


def known_production_project_store_paths() -> tuple[Path, ...]:
    root = _platform_state_root()
    return (root / "creative_projects.json", root / "projects.json")


def _resolve(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(_resolve(left))) == os.path.normcase(str(_resolve(right)))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        _resolve(path).relative_to(_resolve(root))
    except ValueError:
        return False
    return True


def _required_path(env: Mapping[str, str], name: str) -> Path:
    raw = env.get(name, "").strip()
    if not raw:
        raise IntegrationProfileError(
            f"集成验证 profile 缺少必填路径: {name}"
        )
    return Path(raw)


def apply_integration_profile(
    environ: MutableMapping[str, str] | None = None,
) -> dict[str, str | bool] | None:
    """Validate and normalize the profile; return its resolved config.

    ``environ`` is injectable for configuration tests.  Mutations are written
    back to the same mapping so the real process environment is fixed before
    ``app`` submodules import their own flags and paths.
    """
    env = os.environ if environ is None else environ
    if not integration_profile_enabled(env):
        return None

    root = _required_path(env, ISOLATION_ROOT_ENV)
    database = _required_path(env, DATABASE_PATH_ENV)
    project_store = _required_path(env, PROJECT_STORE_ENV)
    production_database = _required_path(env, PRODUCTION_DATABASE_ENV)

    resolved_root = _resolve(root)
    if not resolved_root.exists() or not resolved_root.is_dir():
        raise IntegrationProfileError(
            f"集成验证隔离根不存在或不是目录: {ISOLATION_ROOT_ENV}"
        )

    production_candidates = [
        production_database,
        known_production_database_path(),
    ]
    if _same_path(database, production_database) or any(
        _same_path(database, item) for item in production_candidates
    ):
        raise IntegrationProfileError(
            "集成验证 database 不得指向已知生产数据库"
        )

    production_json_candidates = list(known_production_project_store_paths())
    configured_production_json = env.get(PRODUCTION_PROJECT_STORE_ENV, "").strip()
    if configured_production_json:
        production_json_candidates.append(Path(configured_production_json))
    if any(_same_path(project_store, item) for item in production_json_candidates):
        raise IntegrationProfileError(
            "集成验证 JSON 存储不得指向已知生产 JSON 文件"
        )

    if not _is_relative_to(database, resolved_root):
        raise IntegrationProfileError(
            "集成验证数据库路径必须位于隔离根内: XLINE_DATABASE_PATH"
        )
    if not _is_relative_to(project_store, resolved_root):
        raise IntegrationProfileError(
            "集成验证 JSON 存储路径必须位于隔离根内: XLINE_CREATIVE_PROJECT_STORE"
        )

    # Enforce the offline/virtual boundary before any submodule reads these
    # switches.  Do not use setdefault: integration verification must not be
    # able to inherit a production model or hardware configuration.
    env["XLINE_AGENT_PROVIDER"] = "local"
    env["XLINE_EMBEDDED_DISCOVERY"] = "0"
    env["XLINE_ENABLE_PRINTER"] = "0"
    env["XLINE_RUNTIME_PROFILE"] = "virtual_sim"
    env["XLINE_USE_TOTAL_STATION"] = "0"
    env["XLINE_INTEGRATION_MODEL_CALLS"] = "disabled"
    env["XLINE_INTEGRATION_ROBOT_EXECUTION"] = "disabled"

    return {
        "isolation_root": str(resolved_root),
        "database_path": str(_resolve(database)),
        "project_store_path": str(_resolve(project_store)),
        "production_database_path": str(_resolve(production_database)),
        "model_calls": False,
        "robot_execution": False,
    }


def enforce_integration_profile(environ: MutableMapping[str, str] | None = None) -> None:
    """Call before importing application submodules."""
    apply_integration_profile(environ)


def external_model_calls_permitted(environ: Mapping[str, str] | None = None) -> bool:
    return not integration_profile_enabled(environ)


def robot_execution_permitted(environ: Mapping[str, str] | None = None) -> bool:
    return not integration_profile_enabled(environ)
