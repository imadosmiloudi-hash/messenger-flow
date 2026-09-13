"""Flow send orchestration — only invoked via authenticated API + RQ worker."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.models.entities import (
    AuditLog,
    Customer,
    ExecutionStatus,
    Flow,
    FlowExecution,
    FlowExecutionStep,
    Page,
)
from app.services.events import event_bus


ACTIVE_STATUSES = (ExecutionStatus.QUEUED, ExecutionStatus.RUNNING)


def get_connected_page(db: Session) -> Page:
    page = db.query(Page).filter(Page.is_connected.is_(True)).first()
    if not page:
        raise HTTPException(status_code=400, detail="No connected page. Connect a page first.")
    settings = get_settings()
    # Composio path: Page access token optional
    if settings.uses_composio() or (page.provider or "").lower() == "composio":
        return page
    if not page.access_token:
        raise HTTPException(
            status_code=400,
            detail="No connected Meta page token. Connect a page or configure Composio.",
        )
    return page


def start_flow_execution(
    db: Session,
    flow_id: str,
    customer_id: str,
    user_id: str | None,
    idempotency_key: str | None = None,
) -> FlowExecution:
    """
    Create a QUEUED execution and enqueue RQ job.
    Enforces: only one QUEUED/RUNNING execution per (customer_id, flow_id).
    """
    if idempotency_key:
        existing = (
            db.query(FlowExecution)
            .filter(FlowExecution.idempotency_key == idempotency_key)
            .first()
        )
        if existing:
            return existing

    flow = (
        db.query(Flow)
        .options(joinedload(Flow.steps))
        .filter(Flow.id == flow_id)
        .first()
    )
    if not flow or not flow.is_active:
        raise HTTPException(status_code=404, detail="Flow not found or inactive")
    if not flow.steps:
        raise HTTPException(status_code=400, detail="Flow has no steps")

    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    page = get_connected_page(db)

    # Application-level lock: check for active execution
    # SQLite doesn't support FOR UPDATE well; use transaction + check
    # Application lock + DB check. SELECT FOR UPDATE when dialect supports it.
    q = db.query(FlowExecution).filter(
        FlowExecution.customer_id == customer_id,
        FlowExecution.flow_id == flow_id,
        FlowExecution.status.in_(ACTIVE_STATUSES),
    )
    try:
        if db.bind and db.bind.dialect.name != "sqlite":
            q = q.with_for_update()
    except Exception:
        pass
    active = q.first()
    if active:
        raise HTTPException(
            status_code=409,
            detail="A flow execution is already queued or running for this customer and flow.",
        )

    execution = FlowExecution(
        flow_id=flow.id,
        customer_id=customer.id,
        page_id=page.page_id,
        status=ExecutionStatus.QUEUED,
        current_step_index=0,
        idempotency_key=idempotency_key,
    )
    db.add(execution)
    db.flush()

    for i, step in enumerate(sorted(flow.steps, key=lambda s: s.position)):
        db.add(
            FlowExecutionStep(
                execution_id=execution.id,
                flow_step_id=step.id,
                position=i,
                status=ExecutionStatus.QUEUED,
            )
        )

    db.add(
        AuditLog(
            user_id=user_id,
            action="flow.send",
            entity_type="flow_execution",
            entity_id=execution.id,
            detail=f"flow={flow_id} customer={customer_id}",
        )
    )
    db.commit()
    db.refresh(execution)

    # Enqueue worker — NEVER from webhook path
    from app.workers.tasks import enqueue_flow_execution

    enqueue_flow_execution(execution.id)

    event_bus.publish_sync(
        "execution.queued",
        {"execution_id": execution.id, "flow_id": flow_id, "customer_id": customer_id},
    )
    return (
        db.query(FlowExecution)
        .options(joinedload(FlowExecution.steps))
        .filter(FlowExecution.id == execution.id)
        .one()
    )


def cancel_execution(db: Session, execution_id: str, user_id: str | None) -> FlowExecution:
    execution = db.get(FlowExecution, execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    if execution.status not in ACTIVE_STATUSES:
        raise HTTPException(status_code=400, detail=f"Cannot cancel status {execution.status.value}")
    execution.status = ExecutionStatus.CANCELLED
    execution.finished_at = datetime.now(timezone.utc)
    execution.error_message = "Cancelled by operator"
    db.add(
        AuditLog(
            user_id=user_id,
            action="flow.cancel",
            entity_type="flow_execution",
            entity_id=execution.id,
            detail=None,
        )
    )
    db.commit()
    db.refresh(execution)
    event_bus.publish_sync("execution.cancelled", {"execution_id": execution.id})
    return execution


def retry_execution(db: Session, execution_id: str, user_id: str | None) -> FlowExecution:
    old = (
        db.query(FlowExecution)
        .options(joinedload(FlowExecution.steps))
        .filter(FlowExecution.id == execution_id)
        .first()
    )
    if not old:
        raise HTTPException(status_code=404, detail="Execution not found")
    if old.status not in (ExecutionStatus.FAILED, ExecutionStatus.CANCELLED):
        raise HTTPException(status_code=400, detail="Only failed/cancelled executions can be retried")
    return start_flow_execution(
        db,
        flow_id=old.flow_id,
        customer_id=old.customer_id,
        user_id=user_id,
        idempotency_key=None,
    )
