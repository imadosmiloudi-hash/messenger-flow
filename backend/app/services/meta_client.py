"""Official Meta Graph API client — no unofficial APIs."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import httpx

from app.config import get_settings


class MetaAPIError(Exception):
    def __init__(self, message: str, code: int | None = None, subcode: int | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.subcode = subcode
        self.operator_message = map_meta_error(code, subcode, message)


def map_meta_error(code: int | None, subcode: int | None, raw: str) -> str:
    """Map Meta Graph errors to operator-friendly messages."""
    # Common Meta error codes for Messenger
    if code == 190:
        return "Page access token expired or invalid. Reconnect the page with a fresh token."
    if code == 10 or (code == 200 and subcode in (1545041, None)):
        return "Permission missing. Ensure pages_messaging (and related) permissions are granted."
    if code == 551 or subcode == 1545041:
        return "Outside the 24-hour messaging window. The customer must message you first."
    if code in (100, 2018001) or "attachment" in raw.lower() or "media" in raw.lower():
        if "url" in raw.lower() or "http" in raw.lower():
            return "Unsupported or unreachable media URL. Media must be a public HTTPS URL."
        return "Unsupported media type or invalid attachment."
    if code == 613:
        return "Rate limited by Meta. Wait a moment and retry."
    if "outside" in raw.lower() and "window" in raw.lower():
        return "Outside the 24-hour messaging window. The customer must message you first."
    if "permission" in raw.lower():
        return "Permission missing. Check Meta app review and page permissions."
    return f"Meta API error: {raw}"


def verify_signature(app_secret: str, body: bytes, signature_header: str | None) -> bool:
    """Verify X-Hub-Signature-256 HMAC SHA256."""
    if not signature_header or not app_secret:
        return False
    if not signature_header.startswith("sha256="):
        return False
    expected = signature_header.split("=", 1)[1]
    digest = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, expected)


class MetaClient:
    def __init__(
        self,
        access_token: str | None = None,
        api_version: str | None = None,
        http_client: httpx.Client | None = None,
    ):
        settings = get_settings()
        self.access_token = access_token or settings.meta_page_access_token
        self.base = f"https://graph.facebook.com/{api_version or settings.meta_graph_api_version}"
        self._client = http_client

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.base}{path}"
        params = kwargs.pop("params", {}) or {}
        params["access_token"] = self.access_token
        client = self._client or httpx.Client(timeout=30.0)
        owns = self._client is None
        try:
            resp = client.request(method, url, params=params, **kwargs)
            data = resp.json() if resp.content else {}
            if resp.status_code >= 400 or "error" in data:
                err = data.get("error", {})
                raise MetaAPIError(
                    err.get("message", resp.text or "Unknown Meta error"),
                    code=err.get("code"),
                    subcode=err.get("error_subcode"),
                )
            return data
        finally:
            if owns:
                client.close()

    def send_text(self, page_id: str, recipient_psid: str, text: str) -> dict[str, Any]:
        payload = {
            "recipient": {"id": recipient_psid},
            "messaging_type": "RESPONSE",
            "message": {"text": text},
        }
        return self._request("POST", f"/{page_id}/messages", json=payload)

    def send_attachment(
        self,
        page_id: str,
        recipient_psid: str,
        attachment_type: str,
        url: str,
    ) -> dict[str, Any]:
        if attachment_type not in ("image", "audio", "video", "file"):
            raise MetaAPIError(f"Unsupported attachment type: {attachment_type}")
        payload = {
            "recipient": {"id": recipient_psid},
            "messaging_type": "RESPONSE",
            "message": {
                "attachment": {
                    "type": attachment_type,
                    "payload": {"url": url, "is_reusable": True},
                }
            },
        }
        return self._request("POST", f"/{page_id}/messages", json=payload)

    def get_page_info(self, page_id: str) -> dict[str, Any]:
        return self._request("GET", f"/{page_id}", params={"fields": "id,name"})
