import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class ExecutionStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StepType(str, enum.Enum):
    TEXT = "TEXT"
    IMAGE = "IMAGE"
    AUDIO = "AUDIO"
    VIDEO = "VIDEO"
    DELAY = "DELAY"


class MessageDirection(str, enum.Enum):
    IN = "IN"
    OUT = "OUT"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    page_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    access_token: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(32), default="meta")  # meta|composio
    is_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    page_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    psid: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    profile_pic: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("page_id", "psid", name="uq_customer_page_psid"),)

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="customer")
    messages: Mapped[list["IncomingMessage"]] = relationship(back_populates="customer")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    customer_id: Mapped[str] = mapped_column(String(36), ForeignKey("customers.id"), nullable=False)
    page_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    last_message_preview: Mapped[str] = mapped_column(Text, default="")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unread_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    customer: Mapped["Customer"] = relationship(back_populates="conversations")
    messages: Mapped[list["IncomingMessage"]] = relationship(back_populates="conversation")

    __table_args__ = (
        Index("ix_conversations_last_message_at", "last_message_at"),
    )


class IncomingMessage(Base):
    __tablename__ = "incoming_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    customer_id: Mapped[str] = mapped_column(String(36), ForeignKey("customers.id"), nullable=False)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id"), nullable=False
    )
    page_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    psid: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    meta_message_id: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    direction: Mapped[MessageDirection] = mapped_column(
        Enum(MessageDirection), default=MessageDirection.IN
    )
    message_type: Mapped[str] = mapped_column(String(32), default="text")
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    customer: Mapped["Customer"] = relationship(back_populates="messages")
    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

    __table_args__ = (
        Index("ix_incoming_messages_conv_created", "conversation_id", "created_at"),
    )


class Flow(Base):
    __tablename__ = "flows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    steps: Mapped[list["FlowStep"]] = relationship(
        back_populates="flow", order_by="FlowStep.position", cascade="all, delete-orphan"
    )
    executions: Mapped[list["FlowExecution"]] = relationship(
        back_populates="flow", cascade="all, delete-orphan"
    )


class FlowStep(Base):
    __tablename__ = "flow_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    flow_id: Mapped[str] = mapped_column(String(36), ForeignKey("flows.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    step_type: Mapped[StepType] = mapped_column(Enum(StepType), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)  # text body or media URL
    media_asset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("media_assets.id"), nullable=True
    )
    # JSON array of media asset UUID strings (ordered). Legacy single id kept in media_asset_id.
    media_asset_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    delay_seconds: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    flow: Mapped["Flow"] = relationship(back_populates="steps")
    media_asset: Mapped["MediaAsset | None"] = relationship()


class FlowExecution(Base):
    __tablename__ = "flow_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    flow_id: Mapped[str] = mapped_column(String(36), ForeignKey("flows.id"), nullable=False)
    customer_id: Mapped[str] = mapped_column(String(36), ForeignKey("customers.id"), nullable=False)
    page_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[ExecutionStatus] = mapped_column(
        Enum(ExecutionStatus), default=ExecutionStatus.QUEUED, index=True
    )
    current_step_index: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    flow: Mapped["Flow"] = relationship(back_populates="executions")
    customer: Mapped["Customer"] = relationship()
    steps: Mapped[list["FlowExecutionStep"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_exec_customer_flow_status", "customer_id", "flow_id", "status"),
        Index("ix_exec_customer_status", "customer_id", "status"),
    )


class FlowExecutionStep(Base):
    __tablename__ = "flow_execution_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    execution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("flow_executions.id"), nullable=False
    )
    flow_step_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[ExecutionStatus] = mapped_column(
        Enum(ExecutionStatus), default=ExecutionStatus.QUEUED
    )
    meta_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    execution: Mapped["FlowExecution"] = relationship(back_populates="steps")


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    media_type: Mapped[str] = mapped_column(String(32), nullable=False)  # image|audio|video
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    public_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Setting(Base):
    __tablename__ = "settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
