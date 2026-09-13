"""Mocked Composio HTTP tests for send_text + inbox sync parsing."""

from unittest.mock import MagicMock, patch

from app.config import get_settings
from app.models.entities import Conversation, Customer, IncomingMessage, Page
from app.services.composio_client import (
    ComposioClient,
    extract_message_id,
    parse_conversations_payload,
)


SAMPLE_CONVERSATIONS = {
    "successful": True,
    "error": None,
    "data": {
        "data": [
            {
                "id": "t_1001",
                "updated_time": "2026-09-13T12:00:00+0000",
                "snippet": "Hello from customer",
                "participants": {
                    "data": [
                        {"id": "106896232178599", "name": "IMADS Agency"},
                        {"id": "PSID777", "name": "Alice"},
                    ]
                },
            },
            {
                "id": "t_1002",
                "updated_time": "2026-09-13T11:00:00+0000",
                "snippet": "Second thread",
                "participants": {
                    "data": [
                        {"id": "PSID888", "name": "Bob"},
                        {"id": "106896232178599", "name": "IMADS Agency"},
                    ]
                },
            },
        ]
    },
}


def test_parse_conversations_extracts_psid():
    parsed = parse_conversations_payload(SAMPLE_CONVERSATIONS, "106896232178599")
    assert len(parsed) == 2
    assert parsed[0]["psid"] == "PSID777"
    assert parsed[0]["display_name"] == "Alice"
    assert parsed[1]["psid"] == "PSID888"
    assert "page" not in parsed[0]["psid"].lower()


def test_composio_send_text_http(monkeypatch):
    monkeypatch.setenv("COMPOSIO_API_KEY", "test-composio-key")
    monkeypatch.setenv("COMPOSIO_CONNECTED_ACCOUNT_ID", "facebook_alvar-therm")
    monkeypatch.setenv("MESSAGING_PROVIDER", "composio")
    get_settings.cache_clear()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"successful":true,"data":{"message_id":"m-out-1"}}'
    mock_resp.json.return_value = {
        "successful": True,
        "data": {"message_id": "m-out-1"},
    }

    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp

    client = ComposioClient(http_client=mock_client)
    result = client.send_text("106896232178599", "PSID777", "Hi there")
    assert extract_message_id(result) == "m-out-1"

    assert mock_client.post.called
    args, kwargs = mock_client.post.call_args
    assert "FACEBOOK_SEND_MESSAGE" in args[0]
    headers = kwargs["headers"]
    assert headers["x-api-key"] == "test-composio-key"
    body = kwargs["json"]
    assert body["connected_account_id"] == "facebook_alvar-therm"
    assert body["version"] == "latest"
    assert body["arguments"]["message_text"] == "Hi there"
    assert body["arguments"]["recipient_id"] == "PSID777"

    get_settings.cache_clear()


def test_inbox_sync_upserts(client, auth_headers, db, monkeypatch):
    monkeypatch.setenv("COMPOSIO_API_KEY", "test-composio-key")
    monkeypatch.setenv("COMPOSIO_CONNECTED_ACCOUNT_ID", "facebook_alvar-therm")
    monkeypatch.setenv("MESSAGING_PROVIDER", "composio")
    monkeypatch.setenv("META_PAGE_ID", "106896232178599")
    get_settings.cache_clear()

    page = db.query(Page).filter(Page.page_id == "106896232178599").first()
    if not page:
        page = Page(page_id="106896232178599")
        db.add(page)
    page.name = "IMADS Agency"
    page.provider = "composio"
    page.is_connected = True
    page.access_token = ""
    db.commit()

    msg_payload = {
        "successful": True,
        "data": {
            "data": [
                {
                    "id": "mid-sync-1",
                    "message": "Hello from customer",
                    "created_time": "2026-09-13T12:00:00+00:00",
                    "from": {"id": "PSID777"},
                }
            ]
        },
    }

    with patch("app.api.inbox.ComposioClient") as CC:
        inst = CC.return_value
        inst.list_conversations.return_value = SAMPLE_CONVERSATIONS
        inst.get_conversation_messages.return_value = msg_payload

        r = client.post("/api/inbox/sync", headers=auth_headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["conversations_upserted"] >= 1
        assert data["page_id"] == "106896232178599"

    customers = db.query(Customer).filter(Customer.page_id == "106896232178599").all()
    assert len(customers) >= 2
    psids = {c.psid for c in customers}
    assert "PSID777" in psids
    assert "PSID888" in psids
    assert db.query(Conversation).count() >= 2
    assert db.query(IncomingMessage).count() >= 1

    # Status endpoint
    r2 = client.get("/api/inbox/sync", headers=auth_headers)
    assert r2.status_code == 200
    assert r2.json()["synced_at"] is not None

    get_settings.cache_clear()


def test_connect_composio(client, auth_headers, monkeypatch):
    monkeypatch.setenv("COMPOSIO_API_KEY", "test-composio-key")
    monkeypatch.setenv("META_PAGE_ID", "106896232178599")
    get_settings.cache_clear()

    r = client.post("/api/pages/connect-composio", headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["is_connected"] is True
    assert data["provider"] == "composio"
    assert data["page_id"] == "106896232178599"
    assert data["name"] == "IMADS Agency"
    assert data["has_token"] is False

    get_settings.cache_clear()


def test_send_flow_uses_composio(client, auth_headers, db, monkeypatch):
    monkeypatch.setenv("COMPOSIO_API_KEY", "test-composio-key")
    monkeypatch.setenv("COMPOSIO_CONNECTED_ACCOUNT_ID", "facebook_alvar-therm")
    monkeypatch.setenv("MESSAGING_PROVIDER", "composio")
    get_settings.cache_clear()

    from app.models.entities import Flow

    page = db.query(Page).filter(Page.page_id == "106896232178599").first()
    if not page:
        page = Page(page_id="106896232178599")
        db.add(page)
    page.name = "IMADS Agency"
    page.provider = "composio"
    page.is_connected = True
    cust = Customer(page_id="106896232178599", psid="PSID999", display_name="C")
    db.add(cust)
    db.commit()
    flow = db.query(Flow).filter(Flow.name == "Welcome Flow").first()

    with patch("app.workers.tasks.ComposioClient") as CC:
        inst = CC.return_value
        inst.send_text.return_value = {"successful": True, "data": {"message_id": "c1"}}
        inst.send_media.return_value = {"successful": True, "data": {"message_id": "c2"}}

        r = client.post(
            f"/api/flows/{flow.id}/customers/{cust.id}/send",
            headers={**auth_headers, "Idempotency-Key": "composio-send-1"},
        )
        assert r.status_code == 200, r.text
        assert inst.send_text.called or inst.send_media.called

    get_settings.cache_clear()
