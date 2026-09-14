"""Perf upgrades: inbox light poll / etag, sync coalesce, bulk send."""

from unittest.mock import MagicMock, patch

from app.config import get_settings
from app.models.entities import Customer, ExecutionStatus, Flow, FlowExecution, Page


def test_inbox_etag_304(client, auth_headers, db):
    page = Page(page_id="P-ETAG", name="T", access_token="tok", is_connected=True)
    db.add(page)
    cust = Customer(page_id="P-ETAG", psid="PSID-ETAG", display_name="Etag")
    db.add(cust)
    db.flush()
    from app.models.entities import Conversation
    from datetime import datetime, timezone

    db.add(
        Conversation(
            customer_id=cust.id,
            page_id="P-ETAG",
            last_message_preview="hello",
            last_message_at=datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc),
            unread_count=1,
        )
    )
    db.commit()

    r1 = client.get("/api/inbox", headers=auth_headers)
    assert r1.status_code == 200
    etag = r1.headers.get("ETag")
    assert etag
    assert len(r1.json()) >= 1

    r2 = client.get("/api/inbox", headers={**auth_headers, "If-None-Match": etag})
    assert r2.status_code == 304


def test_inbox_sync_status_without_run_is_light(client, auth_headers, monkeypatch):
    """GET /api/inbox/sync without run=true must NOT call Composio."""
    monkeypatch.setenv("COMPOSIO_API_KEY", "test-key")
    monkeypatch.setenv("MESSAGING_PROVIDER", "composio")
    get_settings.cache_clear()

    with patch("app.api.inbox.ComposioClient") as CC:
        r = client.get("/api/inbox/sync", headers=auth_headers)
        assert r.status_code == 200
        CC.assert_not_called()

    get_settings.cache_clear()


def test_inbox_sync_coalesce_single_flight(client, auth_headers, db, monkeypatch):
    monkeypatch.setenv("COMPOSIO_API_KEY", "test-composio-key")
    monkeypatch.setenv("COMPOSIO_CONNECTED_ACCOUNT_ID", "facebook_alvar-therm")
    monkeypatch.setenv("MESSAGING_PROVIDER", "composio")
    monkeypatch.setenv("META_PAGE_ID", "106896232178599")
    get_settings.cache_clear()

    page = db.query(Page).filter(Page.page_id == "106896232178599").first()
    if not page:
        page = Page(page_id="106896232178599")
        db.add(page)
    page.provider = "composio"
    page.is_connected = True
    db.commit()

    # Force in-process lock path (no Redis)
    with patch("app.api.inbox._try_acquire_sync_lock") as acq:
        # First call: no lock -> coalesced status
        acq.return_value = None
        r = client.post("/api/inbox/sync", headers=auth_headers)
        assert r.status_code == 200
        # Should not raise; returns soft status
        assert "page_id" in r.json()

    get_settings.cache_clear()


def test_send_bulk_and_idempotency(client, auth_headers, db):
    page = Page(page_id="P-BULK", name="Bulk", access_token="tok", is_connected=True)
    db.add(page)
    c1 = Customer(page_id="P-BULK", psid="PSID-B1", display_name="A")
    c2 = Customer(page_id="P-BULK", psid="PSID-B2", display_name="B")
    db.add_all([c1, c2])
    db.commit()
    db.refresh(c1)
    db.refresh(c2)

    flow = db.query(Flow).filter(Flow.name == "Welcome Flow").first()

    with patch("app.workers.tasks.MetaClient") as MC:
        inst = MC.return_value
        inst.send_text.return_value = {"message_id": "out1"}
        inst.send_attachment.return_value = {"message_id": "out2"}

        r = client.post(
            f"/api/flows/{flow.id}/send-bulk",
            headers=auth_headers,
            json={
                "customer_ids": [c1.id, c2.id],
                "idempotency_keys": {c1.id: "bulk-idem-c1", c2.id: "bulk-idem-c2"},
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data["results"]) == 2
        assert all(x["ok"] for x in data["results"])
        exec_ids = {x["execution_id"] for x in data["results"]}
        assert len(exec_ids) == 2

        # Same idempotency keys → same executions, still ok
        r2 = client.post(
            f"/api/flows/{flow.id}/send-bulk",
            headers=auth_headers,
            json={
                "customer_ids": [c1.id],
                "idempotency_keys": {c1.id: "bulk-idem-c1"},
            },
        )
        assert r2.status_code == 200
        assert r2.json()["results"][0]["ok"] is True
        assert r2.json()["results"][0]["execution_id"] in exec_ids


def test_send_bulk_active_guard_reports_error(client, auth_headers, db):
    page = Page(page_id="P-BULK2", name="Bulk2", access_token="tok", is_connected=True)
    db.add(page)
    cust = Customer(page_id="P-BULK2", psid="PSID-BG", display_name="G")
    db.add(cust)
    db.flush()
    flow = db.query(Flow).filter(Flow.name == "Welcome Flow").first()
    db.add(
        FlowExecution(
            flow_id=flow.id,
            customer_id=cust.id,
            page_id="P-BULK2",
            status=ExecutionStatus.RUNNING,
        )
    )
    db.commit()

    r = client.post(
        f"/api/flows/{flow.id}/send-bulk",
        headers=auth_headers,
        json={"customer_ids": [cust.id]},
    )
    assert r.status_code == 200
    item = r.json()["results"][0]
    assert item["ok"] is False
    assert item["error"]
    assert "already" in item["error"].lower() or "queued" in item["error"].lower()


def test_config_operator_defaults():
    get_settings.cache_clear()
    s = get_settings()
    # Defaults or env should be operator-friendly
    assert s.send_rate_limit.endswith("/minute")
    rate_n = int(s.send_rate_limit.split("/")[0])
    assert rate_n >= 120
    assert s.flow_media_gap_ms <= 40
