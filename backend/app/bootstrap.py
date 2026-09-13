"""Startup bootstrap: create tables, admin user, welcome flow, default page."""

from datetime import datetime, timezone

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.models.entities import Flow, FlowStep, Page, StepType, User
from app.security.auth import get_password_hash


WELCOME_STEPS = [
    (StepType.TEXT, "مرحباً بك! أهلاً وسهلاً 👋", None, 1),
    (StepType.TEXT, "شكراً لتواصلك معنا. سنرسل لك معلومات مهمة.", None, 1),
    (StepType.IMAGE, "https://example.com/welcome-image.jpg", None, 2),
    (StepType.TEXT, "إليك شرح سريع لخدماتنا:", None, 1),
    (StepType.AUDIO, "https://example.com/welcome-audio.mp3", None, 2),
    (StepType.TEXT, "يمكنك مشاهدة الفيديو التالي للمزيد من التفاصيل.", None, 1),
    (StepType.VIDEO, "https://example.com/welcome-video.mp4", None, 2),
    (StepType.TEXT, "إذا كان لديك أي سؤال، راسلنا في أي وقت. مع التحية! ✅", None, 0),
]

DEFAULT_COMPOSIO_PAGE_ID = "106896232178599"
DEFAULT_COMPOSIO_PAGE_NAME = "IMADS Agency"


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_page_provider_column()
    db = SessionLocal()
    try:
        ensure_admin(db)
        ensure_welcome_flow(db)
        ensure_default_page(db)
        db.commit()
    finally:
        db.close()


def _ensure_page_provider_column() -> None:
    """Add pages.provider if missing (create_all does not alter existing tables)."""
    try:
        insp = inspect(engine)
        if "pages" not in insp.get_table_names():
            return
        cols = {c["name"] for c in insp.get_columns("pages")}
        if "provider" in cols:
            return
        with engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE pages ADD COLUMN provider VARCHAR(32) DEFAULT 'meta'")
            )
    except Exception:
        # Best-effort; fresh DBs already have the column via create_all
        pass


def ensure_admin(db: Session) -> User:
    settings = get_settings()
    email = settings.admin_email.lower().strip()
    user = db.query(User).filter(User.email == email).first()
    if user:
        return user
    user = User(
        email=email,
        hashed_password=get_password_hash(settings.admin_password),
        is_active=True,
        is_admin=True,
    )
    db.add(user)
    db.flush()
    return user


def ensure_welcome_flow(db: Session) -> Flow:
    existing = db.query(Flow).filter(Flow.name == "Welcome Flow").first()
    if existing:
        return existing
    flow = Flow(
        name="Welcome Flow",
        description="Default 8-step welcome sequence (Arabic placeholders + media URLs).",
        is_active=True,
    )
    db.add(flow)
    db.flush()
    for i, (stype, content, media_id, delay) in enumerate(WELCOME_STEPS):
        db.add(
            FlowStep(
                flow_id=flow.id,
                position=i,
                step_type=stype,
                content=content,
                media_asset_id=media_id,
                delay_seconds=delay,
            )
        )
    db.flush()
    return flow


def ensure_default_page(db: Session) -> Page | None:
    """Seed IMADS Agency page for Composio mode when META_PAGE_ID / defaults apply."""
    settings = get_settings()
    # Only seed when Composio is configured or META_PAGE_ID is explicitly set
    if not settings.uses_composio() and not (settings.meta_page_id or "").strip():
        return None
    page_id = (settings.meta_page_id or DEFAULT_COMPOSIO_PAGE_ID).strip()
    if not page_id:
        return None

    page = db.query(Page).filter(Page.page_id == page_id).first()
    if not page:
        page = Page(page_id=page_id)
        db.add(page)

    # Prefer Composio connection when configured and no other page is connected
    other_connected = (
        db.query(Page)
        .filter(Page.is_connected.is_(True), Page.page_id != page_id)
        .first()
    )
    if settings.uses_composio() and not other_connected:
        page.name = page.name or DEFAULT_COMPOSIO_PAGE_NAME
        if page.page_id == DEFAULT_COMPOSIO_PAGE_ID and not page.name:
            page.name = DEFAULT_COMPOSIO_PAGE_NAME
        if not page.name:
            page.name = DEFAULT_COMPOSIO_PAGE_NAME
        page.provider = "composio"
        page.is_connected = True
        page.connected_at = page.connected_at or datetime.now(timezone.utc)
        # Keep any existing Meta token; Composio does not require it
    elif not page.name and page_id == DEFAULT_COMPOSIO_PAGE_ID:
        page.name = DEFAULT_COMPOSIO_PAGE_NAME

    if page.page_id == DEFAULT_COMPOSIO_PAGE_ID and (
        not page.name or page.name == page_id
    ):
        page.name = DEFAULT_COMPOSIO_PAGE_NAME

    db.flush()
    return page
