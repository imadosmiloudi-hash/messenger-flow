from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

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
    access_token: str


class PageOut(ORMModel):
    id: str
    page_id: str
    name: str
    is_connected: bool
    connected_at: datetime | None
    last_error: str | None
    # Never expose full token
    has_token: bool = False


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
    delay_seconds: int = 0
    position: int | None = None


class FlowStepUpdate(BaseModel):
    step_type: StepType | None = None
    content: str | None = None
    media_asset_id: str | None = None
    delay_seconds: int | None = None
    position: int | None = None


class FlowStepOut(ORMModel):
    id: str
    flow_id: str
    position: int
    step_type: StepType
    content: str | None
    media_asset_id: str | None
    delay_seconds: int


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
    webhook_never_auto_replies: bool = True


class EventPayload(BaseModel):
    type: str
    data: dict[str, Any]
