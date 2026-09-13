import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Isolate test DB before importing app
TEST_DIR = Path("/tmp/messenger_flow_test")
TEST_DIR.mkdir(parents=True, exist_ok=True)
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DIR}/test.db"
os.environ["SECRET_KEY"] = "test-secret-key-for-jwt-signing-only"
os.environ["ADMIN_EMAIL"] = "admin@example.com"
os.environ["ADMIN_PASSWORD"] = "testpass123"
os.environ["META_APP_SECRET"] = "test_app_secret"
os.environ["META_VERIFY_TOKEN"] = "verify_token_test"
os.environ["META_GRAPH_API_VERSION"] = "v26.0"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
os.environ["PUBLIC_BASE_URL"] = "https://example.test"
os.environ["MEDIA_UPLOAD_DIR"] = str(TEST_DIR / "uploads")
os.environ["CORS_ORIGINS"] = "http://localhost:3000"
os.environ["MESSAGING_PROVIDER"] = "meta"
os.environ["COMPOSIO_API_KEY"] = ""
os.environ["META_PAGE_ID"] = ""

# Clear settings cache
from app.config import get_settings

get_settings.cache_clear()

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.bootstrap import init_db  # noqa: E402


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    init_db()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def auth_headers(client):
    r = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "testpass123"},
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
