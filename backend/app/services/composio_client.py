"""Composio HTTP client for Facebook Page messaging tools.

NEVER log API keys or access tokens.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

COMPOSIO_EXECUTE_URL = "https://backend.composio.dev/api/v3.1/tools/execute/{tool_slug}"


class ComposioAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.operator_message = map_composio_error(message, status_code)


def map_composio_error(raw: str, status_code: int | None = None) -> str:
    """Map Composio / Meta-via-Composio errors to operator-friendly messages."""
    text = (raw or "").lower()
    if status_code == 401 or "api key" in text or "unauthorized" in text:
        return "Composio API key invalid or missing. Check COMPOSIO_API_KEY."
    if status_code == 404 or "connected account" in text or "not found" in text:
        return "Composio connected account not found. Check COMPOSIO_CONNECTED_ACCOUNT_ID."
    if status_code == 403 or "permission" in text or "forbidden" in text:
        return "Permission missing on the Composio Facebook connection. Reconnect Facebook in Composio."
    if status_code == 429 or "rate" in text:
        return "Rate limited by Composio or Meta. Wait a moment and retry."
    if "190" in text or "token" in text and ("expired" in text or "invalid" in text):
        return "Facebook token expired in Composio. Reconnect the Facebook account."
    if "551" in text or ("outside" in text and "window" in text) or "24" in text and "hour" in text:
        return "Outside the 24-hour messaging window. The customer must message you first."
    if "attachment" in text or "media" in text or "url" in text and "unreachable" in text:
        return "Unsupported or unreachable media URL. Media must be a public HTTPS URL."
    if raw:
        return f"Composio/Facebook error: {raw}"
    return "Composio request failed."


def _safe_error_text(data: Any, fallback: str) -> str:
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err.get("suggested_fix") or fallback)
        if isinstance(err, str) and err.strip():
            return err
        if data.get("message"):
            return str(data["message"])
    if isinstance(data, str) and data.strip():
        return data
    return fallback


class ComposioClient:
    def __init__(
        self,
        api_key: str | None = None,
        connected_account_id: str | None = None,
        user_id: str | None = None,
        http_client: httpx.Client | None = None,
    ):
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.composio_api_key
        self.connected_account_id = (
            connected_account_id
            if connected_account_id is not None
            else settings.composio_connected_account_id
        )
        self.user_id = user_id if user_id is not None else settings.composio_user_id
        self._client = http_client
        if not self.api_key:
            raise ComposioAPIError("COMPOSIO_API_KEY is not configured", status_code=401)
        if not self.connected_account_id:
            raise ComposioAPIError(
                "COMPOSIO_CONNECTED_ACCOUNT_ID is not configured", status_code=400
            )

    def execute(self, tool_slug: str, arguments: dict[str, Any]) -> dict[str, Any]:
        url = COMPOSIO_EXECUTE_URL.format(tool_slug=tool_slug)
        body: dict[str, Any] = {
            "connected_account_id": self.connected_account_id,
            "arguments": arguments,
            "version": "latest",
        }
        if self.user_id:
            body["user_id"] = self.user_id

        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        # Never log headers or api key
        logger.info("Composio execute tool=%s args_keys=%s", tool_slug, sorted(arguments.keys()))

        client = self._client or httpx.Client(timeout=60.0)
        owns = self._client is None
        try:
            resp = client.post(url, headers=headers, json=body)
            try:
                data = resp.json() if resp.content else {}
            except Exception:
                data = {"error": resp.text or "Non-JSON Composio response"}

            if resp.status_code >= 400:
                raise ComposioAPIError(
                    _safe_error_text(data, resp.text or f"HTTP {resp.status_code}"),
                    status_code=resp.status_code,
                )

            if isinstance(data, dict) and data.get("successful") is False:
                raise ComposioAPIError(
                    _safe_error_text(data, "Tool execution unsuccessful"),
                    status_code=resp.status_code,
                )
            return data if isinstance(data, dict) else {"data": data}
        finally:
            if owns:
                client.close()

    def list_conversations(self, page_id: str, limit: int = 25) -> dict[str, Any]:
        return self.execute(
            "FACEBOOK_GET_PAGE_CONVERSATIONS",
            {
                "page_id": str(page_id),
                "limit": min(limit, 25),
                "fields": "id,updated_time,participants,snippet,message_count",
            },
        )

    def get_conversation_messages(
        self, page_id: str, conversation_id: str, limit: int = 10
    ) -> dict[str, Any]:
        return self.execute(
            "FACEBOOK_GET_CONVERSATION_MESSAGES",
            {
                "page_id": str(page_id),
                "conversation_id": str(conversation_id),
                "limit": min(limit, 25),
                "fields": "id,created_time,from,to,message",
            },
        )

    def send_text(self, page_id: str, recipient_id: str, text: str) -> dict[str, Any]:
        return self.execute(
            "FACEBOOK_SEND_MESSAGE",
            {
                "page_id": str(page_id),
                "recipient_id": str(recipient_id),
                "message_text": text,
                "messaging_type": "RESPONSE",
            },
        )

    def send_media(
        self,
        page_id: str,
        recipient_id: str,
        media_type: str,
        media_url: str,
    ) -> dict[str, Any]:
        mt = (media_type or "").lower()
        if mt not in ("image", "audio", "video", "file"):
            raise ComposioAPIError(f"Unsupported media type: {media_type}")
        return self.execute(
            "FACEBOOK_SEND_MEDIA_MESSAGE",
            {
                "page_id": str(page_id),
                "recipient_id": str(recipient_id),
                "media_type": mt,
                "media_url": media_url,
                "messaging_type": "RESPONSE",
                "is_reusable": True,
            },
        )


def extract_tool_data(result: dict[str, Any]) -> Any:
    """Unwrap Composio execute response to underlying Graph-like payload."""
    data = result.get("data", result)
    # Some tools nest Graph payload under data.data
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], (list, dict)):
        return data
    return data


def extract_message_id(result: dict[str, Any]) -> str | None:
    data = extract_tool_data(result)
    if not isinstance(data, dict):
        return None
    for key in ("message_id", "messageId", "id"):
        if data.get(key):
            return str(data[key])
    nested = data.get("data") if isinstance(data.get("data"), dict) else None
    if nested:
        for key in ("message_id", "messageId", "id"):
            if nested.get(key):
                return str(nested[key])
    return None


def parse_conversations_payload(result: dict[str, Any], page_id: str) -> list[dict[str, Any]]:
    """
    Normalize FACEBOOK_GET_PAGE_CONVERSATIONS into a list of:
      {conversation_id, psid, display_name, updated_time, preview}
    PSID = participant id where id != page_id.
    """
    data = extract_tool_data(result)
    rows: list[Any] = []
    if isinstance(data, dict):
        if isinstance(data.get("data"), list):
            rows = data["data"]
        elif isinstance(data.get("conversations"), list):
            rows = data["conversations"]
    elif isinstance(data, list):
        rows = data

    page_id_s = str(page_id)
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        conv_id = str(row.get("id") or row.get("conversation_id") or "")
        if not conv_id:
            continue
        participants = row.get("participants") or {}
        plist: list[Any]
        if isinstance(participants, dict):
            plist = participants.get("data") or participants.get("participants") or []
        elif isinstance(participants, list):
            plist = participants
        else:
            plist = []

        psid = ""
        display_name = ""
        for p in plist:
            if not isinstance(p, dict):
                continue
            pid = str(p.get("id") or "")
            if pid and pid != page_id_s:
                psid = pid
                display_name = str(p.get("name") or p.get("username") or "")
                break

        if not psid:
            # Fallback keys sometimes present
            psid = str(row.get("psid") or row.get("sender_id") or "")
        if not psid:
            continue

        preview = str(
            row.get("snippet")
            or row.get("preview")
            or row.get("last_message")
            or ""
        )
        updated = row.get("updated_time") or row.get("updated_at") or row.get("updatedTime")
        out.append(
            {
                "conversation_id": conv_id,
                "psid": psid,
                "display_name": display_name or f"User {psid[-6:]}",
                "updated_time": updated,
                "preview": preview,
            }
        )
    return out


def parse_messages_payload(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize FACEBOOK_GET_CONVERSATION_MESSAGES into message dicts."""
    data = extract_tool_data(result)
    rows: list[Any] = []
    if isinstance(data, dict):
        if isinstance(data.get("data"), list):
            rows = data["data"]
        elif isinstance(data.get("messages"), dict) and isinstance(data["messages"].get("data"), list):
            rows = data["messages"]["data"]
        elif isinstance(data.get("messages"), list):
            rows = data["messages"]
    elif isinstance(data, list):
        rows = data

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        mid = str(row.get("id") or "")
        text = row.get("message") or row.get("text") or ""
        from_obj = row.get("from") or {}
        from_id = ""
        if isinstance(from_obj, dict):
            from_id = str(from_obj.get("id") or "")
        created = row.get("created_time") or row.get("created_at")
        out.append(
            {
                "id": mid,
                "text": str(text) if text is not None else "",
                "from_id": from_id,
                "created_time": created,
            }
        )
    return out
