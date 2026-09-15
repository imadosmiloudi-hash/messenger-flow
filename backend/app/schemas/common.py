import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.entities import ExecutionStatus, StepType


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# Auth
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(ORMModel):
    id: str
    email: str
    is_active: bool
    is_admin: bool
    created_at: datetime


# Pages
class PageConnectRequest(BaseModel):
    page_id: str
    name: str = ""
    access_token: str = ""  # optional when provider=composio
    provider: str = "meta"  # meta|composio


class PageOut(ORMModel):
    id: str
    page_id: str
    name: str
    is_connected: bool
    connected_at: datetime | None
    last_error: str | None
    provider: str = "meta"
    # Never expose full token
    has_token: bool = False


class InboxSyncOut(BaseModel):
    ok: bool = True
    page_id: str
    conversations_upserted: int = 0
    messages_upserted: int = 0
    provider: str = "composio"
    synced_at: datetime | None = None
    error: str | None = None


# Inbox
class CustomerOut(ORMModel):
    id: str
    page_id: str
    psid: str
    display_name: str
    last_message_at: datetime | None


class ConversationOut(ORMModel):
    id: str
    customer_id: str
    page_id: str
    last_message_preview: str
    last_message_at: datetime | None
    unread_count: int
    customer: CustomerOut | None = None


class MessageOut(ORMModel):
    id: str
    conversation_id: str
    customer_id: str
    meta_message_id: str | None
    direction: str
    message_type: str
    text: str | None
    created_at: datetime


class ConversationDetailOut(BaseModel):
    conversation: ConversationOut
    messages: list[MessageOut]
    active_execution: "FlowExecutionOut | None" = None


# Flows
class FlowStepCreate(BaseModel):
    step_type: StepType
    content: str | None = None
    media_asset_id: str | None = None
    media_asset_ids: list[str] | None = None
    delay_seconds: int = 0
    position: int | None = None


class FlowStepUpdate(BaseModel):
    step_type: StepType | None = None
    content: str | None = None
    media_asset_id: str | None = None
    media_asset_ids: list[str] | None = None
    delay_seconds: int | None = None
    position: int | None = None


class FlowStepOut(ORMModel):
    id: str
    flow_id: str
    position: int
    step_type: StepType
    content: str | None
    media_asset_id: str | None
    media_asset_ids: list[str] | None = None
    delay_seconds: int

    @field_validator("media_asset_ids", mode="before")
    @classmethod
    def _coerce_media_asset_ids(cls, v):
        if v is None:
            return None
        if isinstance(v, list):
            return [str(x) for x in v if x]
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            try:
                parsed = json.loads(s)
            except json.JSONDecodeError:
                return None
            if isinstance(parsed, list):
                return [str(x) for x in parsed if x]
        return None

    @model_validator(mode="after")
    def _effective_media_ids(self):
        # Effective list = media_asset_ids if non-empty else ([media_asset_id] if set else [])
        if self.media_asset_ids:
            return self
        if self.media_asset_id:
            self.media_asset_ids = [self.media_asset_id]
        else:
            self.media_asset_ids = []
        return self


class FlowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    is_active: bool = True
    steps: list[FlowStepCreate] = []


class FlowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class FlowOut(ORMModel):
    id: str
    name: str
    description: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    steps: list[FlowStepOut] = []


class StepsReorderRequest(BaseModel):
    step_ids: list[str]


# Executions
class FlowExecutionStepOut(ORMModel):
    id: str
    execution_id: str
    flow_step_id: str | None
    position: int
    status: ExecutionStatus
    meta_message_id: str | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None


class FlowExecutionOut(ORMModel):
    id: str
    flow_id: str
    customer_id: str
    page_id: str
    status: ExecutionStatus
    current_step_index: int
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    steps: list[FlowExecutionStepOut] = []


class SendFlowResponse(BaseModel):
    execution: FlowExecutionOut
    queued: bool = True


class BulkSendRequest(BaseModel):
    customer_ids: list[str] = Field(min_length=1)
    # Optional per-customer idempotency keys; server generates when missing
    idempotency_keys: dict[str, str] | None = None


class BulkSendResultItem(BaseModel):
    customer_id: str
    ok: bool
    execution_id: str | None = None
    error: str | None = None


class BulkSendResponse(BaseModel):
    results: list[BulkSendResultItem]


# Media
class MediaAssetOut(ORMModel):
    id: str
    filename: str
    content_type: str
    media_type: str
    size_bytes: int
    public_url: str | None
    created_at: datetime


# Settings / dashboard
class DashboardOut(BaseModel):
    page_connected: bool
    page: PageOut | None
    unread_messages: int
    running_executions: int
    queued_executions: int
    recent_conversations: list[ConversationOut]


class PublicSettingsOut(BaseModel):
    app_name: str
    meta_graph_api_version: str
    meta_verify_token_hint: str
    public_base_url: str
    webhook_url: str
    oauth_redirect_uri: str = ""
    oauth_redirect_host: str = ""
    webhook_never_auto_replies: bool = True
    messaging_provider: str = "meta"
    composio_configured: bool = False
    meta_page_id_default: str = ""


class EventPayload(BaseModel):
    type: str
    data: dict[str, Any]
