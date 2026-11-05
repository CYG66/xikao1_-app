from __future__ import annotations

import tempfile
import unittest
from asyncio import run
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError
from starlette.datastructures import Headers, UploadFile

from app.agent_attachments import AgentAttachmentStore
from app.agent_http_service import _agent_message_with_attachments
from app.routers.agent import upload_agent_image
from app.schemas import AgentChatRequest


class AgentAttachmentTest(unittest.TestCase):
    @staticmethod
    def _png() -> bytes:
        return b"\x89PNG\r\n\x1a\n" + b"test-image-payload"

    def test_image_is_stored_with_public_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentAttachmentStore(Path(directory))
            metadata = store.save_image("site plan.png", "image/png", self._png())

            self.assertEqual(metadata["kind"], "image")
            self.assertEqual(metadata["capability"], "reference_only")
            self.assertNotIn("path", metadata)
            self.assertEqual(store.get(str(metadata["attachment_id"])), metadata)

    def test_invalid_image_content_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentAttachmentStore(Path(directory))
            with self.assertRaisesRegex(ValueError, "扩展名不匹配"):
                store.save_image("fake.png", "image/png", b"not-a-png")

    def test_attachment_schema_requires_server_reference(self) -> None:
        with self.assertRaises(ValidationError):
            AgentChatRequest(
                message="分析图片",
                attachments=[{"kind": "image", "display_name": "site.png"}],
            )

    def test_upload_endpoint_returns_chat_attachment_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentAttachmentStore(Path(directory))
            upload = UploadFile(
                BytesIO(self._png()),
                filename="floor.png",
                headers=Headers({"content-type": "image/png"}),
            )
            with patch("app.routers.agent.agent_attachments", store):
                result = run(upload_agent_image(upload))

        self.assertTrue(result["ok"])
        attachment = result["attachment"]
        self.assertEqual(attachment["kind"], "image")
        self.assertEqual(attachment["display_name"], "floor.png")
        with self.assertRaises(ValidationError):
            AgentChatRequest(
                message="分析图纸",
                attachments=[{"kind": "cad", "display_name": "site.dxf"}],
            )

    def test_verified_image_context_does_not_claim_visual_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentAttachmentStore(Path(directory))
            metadata = store.save_image("site.png", "image/png", self._png())
            command = AgentChatRequest(
                message="给我优化建议",
                attachments=[
                    {
                        "kind": "image",
                        "display_name": "site.png",
                        "attachment_id": metadata["attachment_id"],
                    }
                ],
            )
            with patch("app.agent_http_service.agent_attachments", store):
                message = _agent_message_with_attachments(command)

        self.assertIn("给我优化建议", message)
        self.assertIn("当前文本模型未解析图片像素", message)
        self.assertNotIn(directory, message)


if __name__ == "__main__":
    unittest.main()
