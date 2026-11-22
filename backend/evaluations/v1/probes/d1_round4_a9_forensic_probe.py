"""D1 round-4 zero-cost forensic probe: prove the isolated evaluation process
resolves the CAD planning model to deepseek-flash and injects thinking=disabled
into the real production payload, WITHOUT opening any network socket.

The real HTTP transport (`_deepseek_response`) is replaced by an in-process stub
that records the exact payload the production code built and raises immediately.
No request leaves the process; real_model_calls stays 0.

Usage:
    python d1_round4_a9_forensic_probe.py --backend <combo-backend> --out <snapshot.json>
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import sys
import tempfile


FLASH = "deepseek-flash"


class ForensicNoNetwork(RuntimeError):
    """Raised by the stubbed transport; signals the payload was captured."""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    backend = pathlib.Path(args.backend).resolve()
    iso = pathlib.Path(tempfile.gettempdir()) / "xline-d1-round4"
    iso.mkdir(parents=True, exist_ok=True)

    # Isolation + flash overrides MUST be set before importing the app package.
    os.environ["XLINE_AGENT_PROVIDER"] = "deepseek"
    os.environ["DEEPSEEK_CAD_PLANNING_MODEL"] = FLASH
    os.environ["DEEPSEEK_BASE_MODEL"] = FLASH
    os.environ["DEEPSEEK_ADVANCED_MODEL"] = FLASH
    os.environ["XLINE_CREATIVE_PROJECT_STORE"] = str(iso / "projects.json")
    os.environ["XLINE_AGENT_PLAN_STORE"] = str(iso / "agent_plans.sqlite3")
    os.environ["XLINE_AGENT_USER_CONFIG_PATH"] = str(iso / "users.json")

    sys.path.insert(0, str(backend))

    from app.agent_service import RobotAgentService  # noqa: E402
    from app.request_context import agent_user_scope  # noqa: E402
    from app.structured_usage import structured_usage_scope  # noqa: E402

    owner = "d1-round4-a9"
    captured: dict[str, list[dict]] = {"payloads": []}

    with agent_user_scope(owner):
        service = RobotAgentService(restore_pending_actions=False)

        def stub_transport(payload: dict):
            captured["payloads"].append(
                json.loads(json.dumps(payload, ensure_ascii=False, default=str))
            )
            raise ForensicNoNetwork("forensic: transport stubbed; no socket opened")

        service._deepseek_response = stub_transport

        ledger = {
            "calls": 0,
            "missing_usage_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }
        with structured_usage_scope(ledger):
            try:
                service._structured_review_text(
                    [
                        {"role": "system", "content": "forensic zero-cost payload capture"},
                        {"role": "user", "content": "forensic zero-cost payload capture"},
                    ],
                    mode="advanced",
                    max_tokens_override=8192,
                    model_override=service.cad_planning_model,
                )
            except ForensicNoNetwork:
                pass

    cfg = service.config()
    # Redacted: only boolean flags and model identifiers are recorded; the key
    # itself is never read into the snapshot.
    config_redacted = {
        "mode": cfg.get("mode"),
        "model_legacy": cfg.get("model"),
        "base_model": cfg.get("base_model"),
        "advanced_model": cfg.get("advanced_model"),
        "cad_planning_model": cfg.get("cad_planning_model"),
        "configured": bool(cfg.get("configured")),
        "api_key_configured": bool(cfg.get("api_key_configured")),
        "configured_providers": cfg.get("configured_providers"),
    }

    payload = captured["payloads"][0] if captured["payloads"] else None
    checks = {
        "cad_planning_model_is_flash": service.cad_planning_model == FLASH,
        "base_model_is_flash": service.base_model == FLASH,
        "advanced_model_is_flash": service.advanced_model == FLASH,
        "payload_model_is_flash": bool(payload) and payload.get("model") == FLASH,
        "thinking_disabled_in_payload": bool(payload)
        and payload.get("thinking") == {"type": "disabled"},
        "payload_max_tokens_is_8192": bool(payload)
        and payload.get("max_tokens") == 8192,
        "json_object_response_format": bool(payload)
        and payload.get("response_format") == {"type": "json_object"},
    }

    snapshot = {
        "captured_at_local": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "captured_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "backend": str(backend),
        "owner": owner,
        "isolation_dir": iso.name,
        "env_overrides": {
            "DEEPSEEK_CAD_PLANNING_MODEL": os.environ.get("DEEPSEEK_CAD_PLANNING_MODEL"),
            "DEEPSEEK_BASE_MODEL": os.environ.get("DEEPSEEK_BASE_MODEL"),
            "DEEPSEEK_ADVANCED_MODEL": os.environ.get("DEEPSEEK_ADVANCED_MODEL"),
            "XLINE_CREATIVE_PROJECT_STORE": os.environ.get("XLINE_CREATIVE_PROJECT_STORE"),
            "XLINE_AGENT_PLAN_STORE": os.environ.get("XLINE_AGENT_PLAN_STORE"),
            "XLINE_AGENT_USER_CONFIG_PATH": os.environ.get("XLINE_AGENT_USER_CONFIG_PATH"),
        },
        "config_redacted": config_redacted,
        "payload": None if payload is None else {
            "model": payload.get("model"),
            "thinking": payload.get("thinking"),
            "max_tokens": payload.get("max_tokens"),
            "response_format": payload.get("response_format"),
            "messages_count": len(payload.get("messages") or []),
        },
        "checks": checks,
        "flags": {
            "live_model_calls": 0,
            "network_client_opened": False,
            "transport_stubbed": True,
            "production_module_imported": True,
            "ledger_calls": ledger["calls"],
        },
        "all_checks_pass": all(checks.values()),
    }

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"ok": snapshot["all_checks_pass"], "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if snapshot["all_checks_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
