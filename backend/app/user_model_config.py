from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any


class UserModelConfigStore:
    """Small local store for per-owner model settings.

    The owner id is a request identity today and will be replaced by the
    authenticated account id when account authentication is introduced.
    """

    def __init__(self, path: Path | None = None) -> None:
        configured = os.getenv("XLINE_AGENT_USER_CONFIG_PATH", "").strip()
        self.path = path or Path(configured or (Path.home() / ".config" / "xline-agent-users.json"))
        self._lock = threading.RLock()
        self._profiles: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(payload, dict) and isinstance(payload.get("profiles"), dict):
            self._profiles = {
                str(owner): dict(profile)
                for owner, profile in payload["profiles"].items()
                if isinstance(profile, dict)
            }
            for profile in self._profiles.values():
                if profile.get("mode") == "deepseek":
                    # Older saves forced reasoner without a user choice.
                    profile["advanced_model"] = profile.get("model") or "deepseek-chat"
                    profile.setdefault("cad_planning_model", "deepseek-chat")

    def get(self, owner_id: str) -> dict[str, Any] | None:
        with self._lock:
            profile = self._profiles.get(owner_id)
            return deepcopy(profile) if profile is not None else None

    def update(
        self,
        owner_id: str,
        *,
        mode: str,
        model: str,
        api_key: str | None = None,
        clear_api_key: bool = False,
        cad_planning_model: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            profile = self._profiles.setdefault(owner_id, {"api_keys": {}})
            profile["mode"] = mode
            profile["model"] = model
            profile["base_model"] = model
            profile["advanced_model"] = model
            if cad_planning_model is not None:
                profile["cad_planning_model"] = cad_planning_model
            profile.setdefault("cad_planning_model", "deepseek-chat")
            keys = profile.setdefault("api_keys", {})
            if clear_api_key:
                keys.pop(mode, None)
            elif api_key and api_key.strip():
                keys[mode] = api_key.strip()
            self._save()
            return deepcopy(profile)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"profiles": self._profiles}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass


user_model_config = UserModelConfigStore()
