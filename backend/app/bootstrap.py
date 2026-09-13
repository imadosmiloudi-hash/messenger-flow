"""Startup bootstrap: create tables, admin user, welcome flow."""

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.models.entities import Flow, FlowStep, StepType, User
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


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_admin(db)
        ensure_welcome_flow(db)
        db.commit()
    finally:
        db.close()


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
