"""Facebook OAuth Connect — state, crypto, status safety, select, disconnect."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models.entities import ConnectedAccount, Page, User
from app.security.crypto import decrypt_maybe, decrypt_str, encrypt_str, looks_encrypted
from app.services import facebook_oauth as fb


def test_encrypt_decrypt_roundtrip():
    plain = "EAAG_test_page_token_abc123"
    enc = encrypt_str(plain)
    assert enc != plain
    assert looks_encrypted(enc)
    assert decrypt_str(enc) == plain
    assert decrypt_maybe(enc) == plain
    assert decrypt_maybe(plain) == plain  # legacy plaintext
    assert decrypt_maybe("") == ""
    assert encrypt_str("") == ""


def test_state_validation_rejects_bad_state(client, auth_headers, db):
    # Bad state → redirect to settings error
    r = client.get(
        "/api/integrations/facebook/callback",
        params={"code": "fake", "state": "not-a-real-state"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    loc = r.headers.get("location", "")
    assert "facebook=error" in loc
    assert "invalid_or_expired_state" in loc or "reason=" in loc


def test_status_never_includes_token_fields(client, auth_headers, db):
    user = db.query(User).filter(User.email == "admin@example.com").first()
    assert user
    acct = ConnectedAccount(
        user_id=user.id,
        provider="facebook",
        provider_user_id="999",
        status="connected",
        encrypted_user_access_token=encrypt_str("USER_TOKEN_SECRET"),
        scopes="pages_messaging",
    )
    db.add(acct)
    db.flush()
    page = Page(
        page_id="111222",
        name="Test Page",
        access_token=encrypt_str("PAGE_TOKEN_SECRET"),
        provider="meta",
        is_connected=True,
        connected_account_id=acct.id,
        page_image_url="https://example.com/p.jpg",
        webhook_subscribed=True,
        connection_status="connected",
    )
    db.add(page)
    db.commit()

    r = client.get("/api/integrations/facebook/status", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    blob = json.dumps(data)
    assert "PAGE_TOKEN_SECRET" not in blob
    assert "USER_TOKEN_SECRET" not in blob
    assert "access_token" not in blob
    assert "encrypted_user_access_token" not in blob
    assert data["page"]["page_id"] == "111222"
    assert data["page"]["name"] == "Test Page"
    assert data["page"]["webhook_subscribed"] is True


def test_select_persists_page(client, auth_headers, db):
    user = db.query(User).filter(User.email == "admin@example.com").first()
    acct = ConnectedAccount(
        user_id=user.id,
        provider="facebook",
        status="connected",
        encrypted_user_access_token=encrypt_str("user-tok"),
    )
    db.add(acct)
    db.commit()

    fb.store_pending_pages(
        user.id,
        [
            {
                "page_id": "555666",
                "name": "Select Me",
                "access_token": "page-tok-plain",
                "picture": "https://example.com/x.png",
            }
        ],
    )

    with patch("app.api.integrations_facebook.fb.subscribe_page_webhooks", return_value={"success": True}):
        r = client.post(
            "/api/integrations/facebook/pages/select",
            headers=auth_headers,
            json={"page_id": "555666"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["page"]["page_id"] == "555666"
    assert "access_token" not in json.dumps(body)

    page = db.query(Page).filter(Page.page_id == "555666").first()
    assert page is not None
    assert page.is_connected is True
    assert page.provider == "meta"
    assert page.name == "Select Me"
    assert looks_encrypted(page.access_token)
    assert decrypt_maybe(page.access_token) == "page-tok-plain"
    assert page.webhook_subscribed is True


def test_disconnect_clears(client, auth_headers, db):
    user = db.query(User).filter(User.email == "admin@example.com").first()
    acct = ConnectedAccount(
        user_id=user.id,
        provider="facebook",
        status="connected",
        encrypted_user_access_token=encrypt_str("user-tok"),
    )
    db.add(acct)
    db.flush()
    page = Page(
        page_id="777888",
        name="Bye",
        access_token=encrypt_str("page-tok"),
        provider="meta",
        is_connected=True,
        connected_account_id=acct.id,
        webhook_subscribed=True,
        connection_status="connected",
    )
    db.add(page)
    db.commit()

    with patch("app.api.integrations_facebook.fb.try_unsubscribe_page", return_value=True):
        r = client.post("/api/integrations/facebook/disconnect", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "disconnected"

    db.expire_all()
    page = db.query(Page).filter(Page.page_id == "777888").first()
    assert page.access_token == ""
    assert page.is_connected is False
    assert page.webhook_subscribed is False
    assert page.connection_status == "disconnected"
    acct = (
        db.query(ConnectedAccount)
        .filter(ConnectedAccount.user_id == user.id, ConnectedAccount.provider == "facebook")
        .first()
    )
    assert acct.status == "disconnected"
    assert acct.encrypted_user_access_token is None


def test_connect_requires_meta_app_credentials(client, auth_headers):
    from app.config import get_settings

    get_settings.cache_clear()
    with patch("app.api.integrations_facebook.get_settings") as gs:
        s = MagicMock()
        s.meta_app_id = ""
        s.meta_app_secret = ""
        gs.return_value = s
        r = client.get("/api/integrations/facebook/connect", headers=auth_headers)
    assert r.status_code == 400
    assert "META_APP_ID" in r.json()["detail"]


def test_pages_list_hides_tokens(client, auth_headers, db):
    user = db.query(User).filter(User.email == "admin@example.com").first()
    fb.store_pending_pages(
        user.id,
        [{"page_id": "1", "name": "A", "access_token": "SECRET", "picture": ""}],
    )
    r = client.get("/api/integrations/facebook/pages", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "select"
    blob = json.dumps(data)
    assert "SECRET" not in blob
    assert "access_token" not in blob
    assert data["pages"][0]["page_id"] == "1"


def test_webhook_alias_verify(client):
    r = client.get(
        "/api/webhooks/facebook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "verify_token_test",
            "hub.challenge": "12345",
        },
    )
    assert r.status_code == 200
    assert r.text == "12345"
