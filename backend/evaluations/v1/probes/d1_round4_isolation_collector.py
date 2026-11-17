"""D1 round-4 isolation + raw-response collector (zero-cost, evaluation-only).

This module is evaluation tooling under ``backend/evaluations/v1/probes``. It
does **not** change production business logic. Responsibilities:

1. Redirect every persistent state store to a per-case isolated root **before**
   the app package / module-level singletons are imported.
2. Fail-closed path assertion: every resolved store path must live under the
   isolated root; anything pointing at the shared default store or a real user
   project aborts the run.
3. Write-before-save redaction: ``Authorization`` / API key / secret-shaped
   strings are replaced with ``<redacted>`` before serialization to disk.
4. Usage reconciliation + peak worst-case budget guard with reserve/settle
   release semantics.
5. Raw request/response capture (redacted) for each structured model call.

No network call is made by this module; the budget simulation and path
assertion run offline.
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

FLASH = "deepseek-flash"

# Peak worst-case prices (USD per 1M tokens), controller ruling.
PEAK_INPUT_MISS = 0.30 / 1_000_000
PEAK_INPUT_HIT = 0.006 / 1_000_000
PEAK_OUTPUT = 1.20 / 1_000_000

HARD_LIMITS = {
    "max_cases": 5,
    "max_requests": 30,
    "max_input_tokens": 300_000,
    "max_output_tokens": 60_000,
    "max_cost_usd": 1.00,
}

# Declarative inventory of persistent state.
#
# resolver_ref: production file:line where the env var / default path is read.
# singleton: (module, attribute) holding the import-time singleton; None for a
#   function-resolved directory (resolved by ``path_getter``).
# path_attr: attribute holding the filesystem path on the singleton.
STATE_SPECS: list[dict[str, Any]] = [
    {
        "label": "creative_project_store",
        "env_var": "XLINE_CREATIVE_PROJECT_STORE",
        "filename": "projects.json",
        "resolver_ref": "app/creative_projects.py:69,76",
        "singleton": ("app.creative_projects", "_project_store"),
        "path_attr": "path",
        "default": "temp/xline-agent/creative_projects.json",
    },
    {
        "label": "plan_store",
        "env_var": "XLINE_AGENT_PLAN_STORE",
        "filename": "agent_plans.sqlite3",
        "resolver_ref": "app/agent_plan_runtime.py:40-50,103",
        "singleton": ("app.agent_plan_runtime", "agent_plan_runtime"),
        "path_attr": "store.path",
        "default": "temp/xline-agent/agent_plans.sqlite3",
    },
    {
        "label": "user_model_config",
        "env_var": "XLINE_AGENT_USER_CONFIG_PATH",
        "filename": "users.json",
        "resolver_ref": "app/user_model_config.py:19-20",
        "singleton": ("app.user_model_config", "user_model_config"),
        "path_attr": "path",
        "default": "~/.config/xline-agent-users.json",
    },
    {
        "label": "conversation_memory",
        "env_var": "XLINE_AGENT_MEMORY_STORE",
        "filename": "conversation_memory.json",
        "resolver_ref": "app/conversation_memory.py:78-85",
        "singleton": ("app.conversation_memory", "conversation_memory"),
        "path_attr": "path",
        "default": "temp/xline-agent/conversation_memory.json",
    },
    {
        "label": "run_store",
        "env_var": "XLINE_AGENT_RUN_STORE",
        "filename": "agent_runs.json",
        "resolver_ref": "app/agent_run_store.py:54-61",
        "singleton": ("app.agent_run_store", "agent_runs"),
        "path_attr": "path",
        "default": "temp/xline-agent/agent_runs.json",
    },
    {
        "label": "task_store",
        "env_var": "XLINE_AGENT_TASK_STORE",
        "filename": "tasks.json",
        "resolver_ref": "app/task_store.py:48-55",
        "singleton": ("app.task_store", "agent_tasks"),
        "path_attr": "path",
        "default": "temp/xline-agent/tasks.json",
    },
    {
        "label": "audit_jsonl",
        "env_var": "XLINE_AGENT_AUDIT_STORE",
        "filename": "agent_audit.jsonl",
        "resolver_ref": "app/audit_store.py:18-27",
        "singleton": ("app.audit_store", "agent_audit"),
        "path_attr": "path",
        "default": "temp/xline-agent/agent_audit.jsonl",
    },
    {
        "label": "history_database",
        "env_var": "XLINE_DATABASE_PATH",
        "filename": "xline.db",
        "resolver_ref": "app/database.py:22-26,36",
        "singleton": ("app.database", "xline_database"),
        "path_attr": "path",
        "default": "temp/xline-agent/xline.db",
    },
    {
        "label": "attachments_dir",
        "env_var": "XLINE_AGENT_ATTACHMENTS_DIR",
        "filename": "attachments",
        "resolver_ref": "app/agent_attachments.py:21-29",
        "singleton": ("app.agent_attachments", "agent_attachments"),
        "path_attr": "root",
        "default": "temp/xline-agent/attachments",
    },
    {
        "label": "drawing_versions",
        "env_var": "XLINE_DRAWING_VERSION_STORE",
        "filename": "drawing_versions.json",
        "resolver_ref": "app/drawing_versions.py:28-30",
        "singleton": ("app.drawing_versions", "drawing_versions"),
        "path_attr": "path",
        "default": "temp/xline-agent/drawing_versions.json",
    },
    {
        "label": "mission_ledger",
        "env_var": "XLINE_MISSION_LEDGER_STORE",
        "filename": "mission_ledger.json",
        "resolver_ref": "app/mission_ledger.py:19-26",
        "singleton": ("app.mission_ledger", "mission_ledger"),
        "path_attr": "path",
        "default": "temp/xline-agent/mission_ledger.json",
    },
    {
        "label": "cad_directory",
        "env_var": "XLINE_CAD_DIR",
        "filename": "cad",
        "resolver_ref": "app/drawing_store.py:17-23",
        "singleton": None,
        "path_attr": None,
        "default": "XLINE_WS_DIR/cad",
    },
]

SECRET_KEY_NAMES = {"api_key", "apikey", "authorization", "key", "token", "secret", "api-keys"}
# Secret-shaped strings. Applied to string values before they touch disk.
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{12,}", re.IGNORECASE),
    re.compile(r"(?i)(api[_-]?key|authorization|token)\s*[:=]\s*[\"']?[A-Za-z0-9._\-]{12,}"),
]


class IsolationViolation(RuntimeError):
    """Raised fail-closed when a resolved store escapes the isolated root."""


class BudgetExceeded(RuntimeError):
    """Raised when a worst-case reserve would break a hard limit."""


class UsageMissing(RuntimeError):
    """Raised when a response lacks a usable usage block."""


# --------------------------------------------------------------------------- #
# Isolation environment
# --------------------------------------------------------------------------- #


def prepare_isolation_env(iso_root: pathlib.Path, case_id: str) -> dict[str, str]:
    """Build and apply per-case isolation env vars **before** app import.

    Returns the applied mapping. Every state path lives under
    ``iso_root / case_id``. Model overrides are NOT state isolation and are
    left to the runner.
    """
    root = pathlib.Path(iso_root).resolve() / case_id
    root.mkdir(parents=True, exist_ok=True)
    env: dict[str, str] = {}
    for spec in STATE_SPECS:
        target = root / spec["filename"]
        if spec["path_attr"] == "root" or spec["filename"] in {"attachments", "cad"}:
            target.mkdir(parents=True, exist_ok=True)
        env[spec["env_var"]] = str(target)
    for key, value in env.items():
        os.environ[key] = value
    return env


def _resolve_attr(obj: Any, dotted: str) -> Any:
    current = obj
    for part in dotted.split("."):
        current = getattr(current, part)
    return current


def resolve_state_paths(backend: pathlib.Path) -> list[dict[str, Any]]:
    """Import the store modules (no service/HTTP client) and read resolved paths.

    Must be called after :func:`prepare_isolation_env`. The store singletons are
    constructed at import time, so env vars are read before their ``__init__``.
    """
    backend = pathlib.Path(backend).resolve()
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))

    resolved: list[dict[str, Any]] = []
    for spec in STATE_SPECS:
        if spec["singleton"] is None:
            # Function-resolved directory: import the module and call the getter.
            from app import drawing_store  # noqa: PLC0415

            path = pathlib.Path(drawing_store.cad_directory()).resolve()
            resolved.append({"label": spec["label"], "env_var": spec["env_var"],
                             "resolved": str(path), "resolver_ref": spec["resolver_ref"]})
            continue
        module_name, attr = spec["singleton"]
        module = __import__(module_name, fromlist=[attr])
        singleton = getattr(module, attr)
        path = pathlib.Path(_resolve_attr(singleton, spec["path_attr"])).resolve()
        resolved.append({"label": spec["label"], "env_var": spec["env_var"],
                         "resolved": str(path), "resolver_ref": spec["resolver_ref"]})
    return resolved


def assert_within_root(iso_root: pathlib.Path, case_id: str,
                       resolved: list[dict[str, Any]]) -> None:
    """Fail-closed: every resolved path must be under the isolated root."""
    root = pathlib.Path(iso_root).resolve() / case_id
    violations: list[dict[str, str]] = []
    for entry in resolved:
        path = pathlib.Path(entry["resolved"]).resolve()
        try:
            inside = path.is_relative_to(root)
        except OSError:
            inside = False
        if not inside:
            violations.append({"label": entry["label"], "env_var": entry["env_var"],
                               "resolved": entry["resolved"], "root": str(root)})
    if violations:
        raise IsolationViolation(json.dumps(violations, ensure_ascii=False, indent=2))


# --------------------------------------------------------------------------- #
# Redaction
# --------------------------------------------------------------------------- #


def _redact_string(text: str) -> str:
    out = text
    for pattern in SECRET_PATTERNS:
        out = pattern.sub("<redacted>", out)
    return out


def redact(value: Any) -> Any:
    """Recursive write-before-save redaction. Never mutates the input."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in SECRET_KEY_NAMES:
                out[str(key)] = "<redacted>"
            else:
                out[str(key)] = redact(item)
        return out
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def assert_no_secret_shape(text: str) -> None:
    """Self-check: raise if a secret-shaped token remains in serialized text."""
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            raise IsolationViolation(f"secret shape remains: {pattern.pattern}")


# --------------------------------------------------------------------------- #
# Budget guard + reconciliation
# --------------------------------------------------------------------------- #


@dataclass
class BudgetGuard:
    limits: dict[str, int | float] = field(default_factory=lambda: dict(HARD_LIMITS))
    settled_requests: int = 0
    settled_input_tokens: int = 0
    settled_output_tokens: int = 0
    settled_cost_usd: float = 0.0
    pending_reserve_usd: float = 0.0
    pending_reserve_input: int = 0
    pending_reserve_output: int = 0

    def reserve(self, input_estimate: int, max_output_tokens: int) -> dict[str, Any]:
        """Worst-case peak reserve before a request; fail-closed on limit."""
        worst_cost = (input_estimate * PEAK_INPUT_MISS + max_output_tokens * PEAK_OUTPUT)
        reasons: list[str] = []
        if self.settled_cost_usd + worst_cost > self.limits["max_cost_usd"]:
            reasons.append("cost")
        if self.settled_input_tokens + input_estimate > self.limits["max_input_tokens"]:
            reasons.append("input_tokens")
        if self.settled_output_tokens + max_output_tokens > self.limits["max_output_tokens"]:
            reasons.append("output_tokens")
        if self.settled_requests + 1 > self.limits["max_requests"]:
            reasons.append("requests")
        if reasons:
            raise BudgetExceeded(f"worst-case reserve breaks limits: {reasons}")
        self.pending_reserve_usd = worst_cost
        self.pending_reserve_input = input_estimate
        self.pending_reserve_output = max_output_tokens
        return {
            "worst_cost_usd": round(worst_cost, 10),
            "worst_input_tokens": input_estimate,
            "worst_output_tokens": max_output_tokens,
            "peak": True,
        }

    def settle(self, usage: dict[str, Any], expected_model: str = FLASH,
               response_model: str | None = None) -> dict[str, Any]:
        """Settle real usage, release the unused reserve, reconcile.

        Raises UsageMissing / BudgetExceeded on missing or inconsistent data.
        """
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        if prompt is None or completion is None:
            raise UsageMissing(f"usage incomplete: {redact(usage)}")
        prompt = int(prompt)
        completion = int(completion)
        hit = int(usage.get("prompt_cache_hit_tokens") or 0)
        miss = prompt - hit if hit > 0 else prompt
        if miss < 0:
            raise UsageMissing("cache hit exceeds prompt tokens")
        cost = miss * PEAK_INPUT_MISS + hit * PEAK_INPUT_HIT + completion * PEAK_OUTPUT

        if response_model is not None and response_model != expected_model:
            raise IsolationViolation(
                f"response model {response_model!r} != expected {expected_model!r}")

        # Release pending reserve, then add settled real usage.
        self.pending_reserve_usd = 0.0
        self.pending_reserve_input = 0
        self.pending_reserve_output = 0
        self.settled_requests += 1
        self.settled_input_tokens += prompt
        self.settled_output_tokens += completion
        self.settled_cost_usd += cost

        if (self.settled_cost_usd > self.limits["max_cost_usd"]
                or self.settled_input_tokens > self.limits["max_input_tokens"]
                or self.settled_output_tokens > self.limits["max_output_tokens"]
                or self.settled_requests > self.limits["max_requests"]):
            raise BudgetExceeded("settled usage broke a hard limit")

        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "cache_hit_tokens": hit,
            "cache_miss_tokens": miss,
            "input_cost_usd": round(miss * PEAK_INPUT_MISS + hit * PEAK_INPUT_HIT, 10),
            "output_cost_usd": round(completion * PEAK_OUTPUT, 10),
            "total_cost_usd": round(cost, 10),
        }

    def remaining(self) -> dict[str, float]:
        return {
            "cost_usd": round(self.limits["max_cost_usd"] - self.settled_cost_usd, 10),
            "requests": self.limits["max_requests"] - self.settled_requests,
            "input_tokens": self.limits["max_input_tokens"] - self.settled_input_tokens,
            "output_tokens": self.limits["max_output_tokens"] - self.settled_output_tokens,
        }


# --------------------------------------------------------------------------- #
# Raw response recorder
# --------------------------------------------------------------------------- #


class RawResponseRecorder:
    """Capture redacted request metadata + response, one JSONL line per call."""

    def __init__(self, out_path: pathlib.Path) -> None:
        self.out_path = pathlib.Path(out_path)
        self.entries: list[dict[str, Any]] = []

    @staticmethod
    def request_metadata(payload: dict[str, Any]) -> dict[str, Any]:
        """Extract non-secret request metadata; headers/keys are never copied."""
        messages = payload.get("messages") or []
        tools = payload.get("tools") or payload.get("functions") or []
        return redact({
            "model": payload.get("model"),
            "thinking": payload.get("thinking"),
            "max_tokens": payload.get("max_tokens"),
            "response_format": payload.get("response_format"),
            "messages_count": len(messages),
            "tools_count": len(tools) if isinstance(tools, list) else 0,
        })

    def record(self, payload: dict[str, Any], response: dict[str, Any],
               expected_model: str = FLASH) -> dict[str, Any]:
        choices = response.get("choices") or [{}]
        message = (choices[0].get("message") or {}) if choices else {}
        content = message.get("content")
        if isinstance(content, list):
            content = " ".join(str(part) for part in content)
        entry = {
            "captured_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "request": self.request_metadata(payload),
            "response": redact({
                "request_id": response.get("id") or "not_available",
                "model": response.get("model") or "not_available",
                "finish_reason": (choices[0].get("finish_reason") if choices else None),
                "usage": response.get("usage"),
                "content_excerpt": str(content)[:500] if content else None,
            }),
            "guard": {
                "model_matches_expected": response.get("model") == expected_model,
            },
        }
        self.entries.append(entry)
        return entry

    def flush(self) -> None:
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        with self.out_path.open("w", encoding="utf-8") as fh:
            for entry in self.entries:
                line = json.dumps(redact(entry), ensure_ascii=False)
                assert_no_secret_shape(line)
                fh.write(line + "\n")
