"""Startup bootstrap: create tables, admin user, welcome flow, default page."""

from datetime import datetime, timezone

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.models.entities import ConnectedAccount, Flow, FlowStep, OAuthState, Page, StepType, User
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
    _ensure_oauth_tables()
    _ensure_page_provider_column()
    _ensure_page_oauth_columns()
    _ensure_flow_step_media_asset_ids_column()
    _ensure_performance_indexes()
    db = SessionLocal()
    try:
        ensure_admin(db)
        ensure_welcome_flow(db)
        ensure_default_page(db)
        db.commit()
    finally:
        db.close()


def _ensure_oauth_tables() -> None:
    """Ensure connected_accounts + oauth_states exist even if create_all skipped them."""
    ddl = [
        """
        CREATE TABLE IF NOT EXISTS connected_accounts (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id),
            provider VARCHAR(32) NOT NULL DEFAULT 'facebook',
            provider_user_id VARCHAR(128),
            status VARCHAR(32) NOT NULL DEFAULT 'disconnected',
            encrypted_user_access_token TEXT,
            token_expires_at TIMESTAMP WITH TIME ZONE,
            scopes TEXT,
            last_error TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS oauth_states (
            state VARCHAR(128) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL,
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_connected_account_user_provider ON connected_accounts (user_id, provider)",
    ]
    # SQLite-friendly variants without WITH TIME ZONE if needed — try Postgres first then soft-fail
    with engine.begin() as conn:
        dialect = engine.dialect.name
        for stmt in ddl:
            sql = stmt
            if dialect == "sqlite":
                sql = (
                    sql.replace("TIMESTAMP WITH TIME ZONE", "TIMESTAMP")
                    .replace("DEFAULT NOW()", "DEFAULT CURRENT_TIMESTAMP")
                    .replace("REFERENCES users(id)", "")
                )
            try:
                conn.execute(text(sql))
            except Exception:
                # Table/index may already exist with slightly different shape
                pass


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



def _ensure_page_oauth_columns() -> None:
    """Add OAuth-related pages columns if missing (create_all does not alter existing tables)."""
    insp = inspect(engine)
    try:
        insp.clear_cache()
    except Exception:
        pass
    if "pages" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("pages")}
    # Postgres-safe defaults (avoid BOOLEAN DEFAULT 0 quirks across dialects)
    wanted = [
        ("connected_account_id", "ALTER TABLE pages ADD COLUMN connected_account_id VARCHAR(36)"),
        ("page_image_url", "ALTER TABLE pages ADD COLUMN page_image_url TEXT"),
        (
            "webhook_subscribed",
            "ALTER TABLE pages ADD COLUMN webhook_subscribed BOOLEAN DEFAULT FALSE",
        ),
        (
            "connection_status",
            "ALTER TABLE pages ADD COLUMN connection_status VARCHAR(32) DEFAULT 'disconnected'",
        ),
    ]
    for name, stmt in wanted:
        if name in cols:
            continue
        with engine.begin() as conn:
            conn.execute(text(stmt))
        cols.add(name)


def _ensure_flow_step_media_asset_ids_column() -> None:
    """Add flow_steps.media_asset_ids if missing (create_all does not alter existing tables)."""
    try:
        insp = inspect(engine)
        if "flow_steps" not in insp.get_table_names():
            return
        cols = {c["name"] for c in insp.get_columns("flow_steps")}
        if "media_asset_ids" in cols:
            return
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE flow_steps ADD COLUMN media_asset_ids TEXT"))
    except Exception:
        # Best-effort; fresh DBs already have the column via create_all
        pass



def _ensure_performance_indexes() -> None:
    """Create commonly queried indexes if missing (safe for SQLite + Postgres)."""
    statements = [
        "CREATE INDEX IF NOT EXISTS ix_conversations_last_message_at ON conversations (last_message_at)",
        "CREATE INDEX IF NOT EXISTS ix_incoming_messages_conv_created ON incoming_messages (conversation_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_exec_customer_status ON flow_executions (customer_id, status)",
    ]
    try:
        insp = inspect(engine)
        tables = set(insp.get_table_names())
        with engine.begin() as conn:
            for stmt in statements:
                if "conversations" in stmt and "conversations" not in tables:
                    continue
                if "incoming_messages" in stmt and "incoming_messages" not in tables:
                    continue
                if "flow_executions" in stmt and "flow_executions" not in tables:
                    continue
                try:
                    conn.execute(text(stmt))
                except Exception:
                    pass
    except Exception:
        pass


def ensure_admin(db: Session) -> User:
    """Create or sync the operator admin from ADMIN_EMAIL / ADMIN_PASSWORD."""
    settings = get_settings()
    email = settings.admin_email.lower().strip()
    password_hash = get_password_hash(settings.admin_password)

    user = db.query(User).filter(User.email == email).first()
    if user:
        user.hashed_password = password_hash
        user.is_active = True
        user.is_admin = True
        db.flush()
        return user

    # Migrate the original bootstrap admin email if still present
    legacy = db.query(User).filter(User.email == "admin@example.com").first()
    if legacy:
        legacy.email = email
        legacy.hashed_password = password_hash
        legacy.is_active = True
        legacy.is_admin = True
        db.flush()
        return legacy

    user = User(
        email=email,
        hashed_password=password_hash,
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
