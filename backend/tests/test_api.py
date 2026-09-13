import io
from unittest.mock import MagicMock, patch

from app.models.entities import Customer, ExecutionStatus, Flow, FlowExecution, Page
from app.services.meta_client import MetaAPIError, MetaClient


def test_auth_login_me(client, auth_headers):
    r = client.get("/api/auth/me", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["email"] == "admin@example.com"


def test_auth_fail(client):
    r = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "wrong"})
    assert r.status_code == 401


def test_protected_without_token(client):
    assert client.get("/api/flows").status_code == 401


def test_flow_crud(client, auth_headers):
    r = client.get("/api/flows", headers=auth_headers)
    assert r.status_code == 200
    flows = r.json()
    assert any(f["name"] == "Welcome Flow" for f in flows)
    welcome = next(f for f in flows if f["name"] == "Welcome Flow")
    assert len(welcome["steps"]) == 8

    r = client.post(
        "/api/flows",
        headers=auth_headers,
        json={
            "name": "Test Flow",
            "description": "d",
            "steps": [
                {"step_type": "TEXT", "content": "Hi", "delay_seconds": 0},
                {"step_type": "DELAY", "delay_seconds": 1},
            ],
        },
    )
    assert r.status_code == 201
    flow_id = r.json()["id"]

    r = client.patch(
        f"/api/flows/{flow_id}",
        headers=auth_headers,
        json={"name": "Test Flow Renamed"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Test Flow Renamed"

    r = client.post(f"/api/flows/{flow_id}/duplicate", headers=auth_headers)
    assert r.status_code == 201
    assert "(copy)" in r.json()["name"]


def test_send_and_duplicate_409(client, auth_headers, db):
    # Setup page + customer
    page = Page(page_id="P1", name="Test", access_token="tok", is_connected=True)
    db.add(page)
    cust = Customer(page_id="P1", psid="PSID999", display_name="C")
    db.add(cust)
    db.commit()

    flow = db.query(Flow).filter(Flow.name == "Welcome Flow").first()

    with patch("app.workers.tasks.MetaClient") as MC:
        inst = MC.return_value
        inst.send_text.return_value = {"message_id": "out1"}
        inst.send_attachment.return_value = {"message_id": "out2"}

        r = client.post(
            f"/api/flows/{flow.id}/customers/{cust.id}/send",
            headers={**auth_headers, "Idempotency-Key": "idem-1"},
        )
        assert r.status_code == 200
        exec_id = r.json()["execution"]["id"]

        # Same idempotency key returns same execution
        r2 = client.post(
            f"/api/flows/{flow.id}/customers/{cust.id}/send",
            headers={**auth_headers, "Idempotency-Key": "idem-1"},
        )
        assert r2.status_code == 200
        assert r2.json()["execution"]["id"] == exec_id

    # Force a QUEUED execution for 409
    db.add(
        FlowExecution(
            flow_id=flow.id,
            customer_id=cust.id,
            page_id="P1",
            status=ExecutionStatus.QUEUED,
        )
    )
    db.commit()
    r3 = client.post(
        f"/api/flows/{flow.id}/customers/{cust.id}/send",
        headers={**auth_headers, "Idempotency-Key": "idem-2"},
    )
    assert r3.status_code == 409


def test_cancel(client, auth_headers, db):
    page = Page(page_id="P2", name="T", access_token="tok", is_connected=True)
    db.add(page)
    cust = Customer(page_id="P2", psid="PSID888", display_name="C")
    db.add(cust)
    db.flush()
    flow = db.query(Flow).filter(Flow.name == "Welcome Flow").first()
    ex = FlowExecution(
        flow_id=flow.id,
        customer_id=cust.id,
        page_id="P2",
        status=ExecutionStatus.RUNNING,
    )
    db.add(ex)
    db.commit()

    r = client.post(f"/api/executions/{ex.id}/cancel", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "CANCELLED"


def test_media_validation(client, auth_headers):
    # Bad type
    r = client.post(
        "/api/media/upload",
        headers=auth_headers,
        files={"file": ("x.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
    )
    assert r.status_code == 400

    r = client.post(
        "/api/media/upload",
        headers=auth_headers,
        files={"file": ("pic.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 100), "image/png")},
    )
    assert r.status_code == 201
    assert r.json()["media_type"] == "image"


def test_pages_connect(client, auth_headers):
    with patch.object(MetaClient, "get_page_info", return_value={"id": "99", "name": "My Page"}):
        r = client.post(
            "/api/pages/connect",
            headers=auth_headers,
            json={"page_id": "99", "name": "", "access_token": "PAGE_TOKEN"},
        )
    assert r.status_code == 200
    assert r.json()["is_connected"] is True
    assert r.json()["has_token"] is True

    r = client.get("/api/pages/status", headers=auth_headers)
    assert r.status_code == 200


def test_inbox_after_webhook(client, auth_headers, db):
    import hashlib
    import hmac
    import json

    payload = {
        "object": "page",
        "entry": [
            {
                "id": "PAGE1",
                "messaging": [
                    {
                        "sender": {"id": "PSID333"},
                        "message": {"mid": "m-inbox", "text": "Inbox hi"},
                    }
                ],
            }
        ],
    }
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"test_app_secret", body, hashlib.sha256).hexdigest()
    client.post("/webhook", content=body, headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig})

    r = client.get("/api/inbox", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["webhook_auto_reply"] is False
