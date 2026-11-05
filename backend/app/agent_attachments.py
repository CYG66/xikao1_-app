from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from uuid import uuid4

MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


class AgentAttachmentStore:
    def __init__(self, root: Path | None = None) -> None:
        configured = os.getenv("XLINE_AGENT_ATTACHMENTS_DIR", "").strip()
        default_root = (
            Path(tempfile.gettempdir()) / "xline-agent" / "attachments"
            if os.name == "nt"
            else Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state"))
            / "xline-agent"
            / "attachments"
        )
        self.root = root or (Path(configured) if configured else default_root)

    @staticmethod
    def _valid_signature(payload: bytes, suffix: str) -> bool:
        if suffix == ".png":
            return payload.startswith(b"\x89PNG\r\n\x1a\n")
        if suffix in {".jpg", ".jpeg"}:
            return payload.startswith(b"\xff\xd8\xff")
        if suffix == ".webp":
            return len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP"
        return False

    def save_image(self, file_name: str, content_type: str, payload: bytes) -> dict[str, object]:
        suffix = Path(file_name).suffix.lower()
        expected_type = IMAGE_TYPES.get(suffix)
        if expected_type is None:
            raise ValueError("仅支持 JPG、PNG 或 WebP 图片。")
        if not payload:
            raise ValueError("图片内容为空。")
        if len(payload) > MAX_IMAGE_BYTES:
            raise ValueError("图片不能超过 10 MB。")
        if content_type and content_type not in {expected_type, "application/octet-stream"}:
            raise ValueError("图片格式与文件类型不一致。")
        if not self._valid_signature(payload, suffix):
            raise ValueError("图片内容无效或扩展名不匹配。")

        attachment_id = uuid4().hex
        safe_name = re.sub(r"[^A-Za-z0-9_.\-\u4e00-\u9fff]", "_", Path(file_name).name)
        self.root.mkdir(parents=True, exist_ok=True)
        image_path = self.root / f"{attachment_id}{suffix}"
        metadata_path = self.root / f"{attachment_id}.json"
        image_path.write_bytes(payload)
        metadata = {
            "attachment_id": attachment_id,
            "kind": "image",
            "display_name": safe_name or f"image{suffix}",
            "mime_type": expected_type,
            "size": len(payload),
            "suffix": suffix,
            "capability": "reference_only",
        }
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
        return metadata

    def get(self, attachment_id: str) -> dict[str, object] | None:
        if not re.fullmatch(r"[a-f0-9]{16,64}", attachment_id):
            return None
        metadata_path = self.root / f"{attachment_id}.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(metadata, dict) or metadata.get("attachment_id") != attachment_id:
            return None
        suffix = str(metadata.get("suffix") or "")
        if suffix not in IMAGE_TYPES or not (self.root / f"{attachment_id}{suffix}").is_file():
            return None
        return metadata


agent_attachments = AgentAttachmentStore()
