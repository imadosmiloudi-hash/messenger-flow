"""RQ worker tasks for sequential flow execution."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from redis import Redis
from rq import Queue
from sqlalchemy.orm import joinedload

from app.config import get_settings
from app.db import SessionLocal
from app.models.entities import (
    ExecutionStatus,
    Flow,
    FlowExecution,
    FlowExecutionStep,
    Page,
    StepType,
)
from app.services.composio_client import (
    ComposioAPIError,
    ComposioClient,
    extract_message_id,
)
from app.services.events import event_bus
from app.services.meta_client import MetaAPIError, MetaClient


def get_queue() -> Queue:
    settings = get_settings()
    return Queue("messenger", connection=Redis.from_url(settings.redis_url))


def enqueue_flow_execution(execution_id: str) -> str | None:
    """Enqueue job. If Redis unavailable (e.g. tests), run inline when APP_ENV=test."""
    settings = get_settings()
    if settings.app_env == "test":
        run_flow_execution(execution_id)
        return None
    try:
        job = get_queue().enqueue(
            "app.workers.tasks.run_flow_execution",
            execution_id,
            job_timeout=3600,
            result_ttl=86400,
        )
        return job.id
    except Exception:
        # Dev fallback without Redis: run synchronously (not for production)
        if settings.app_env == "development":
            run_flow_execution(execution_id)
            return None
        raise


def _use_composio(page: Page) -> bool:
    settings = get_settings()
    if settings.uses_composio():
        return True
    return (page.provider or "").lower() == "composio" and bool(settings.composio_api_key)


def _media_gap_seconds() -> float:
    """Tiny gap between sequential media sends to avoid Meta/Composio hard rate-limit fails."""
    try:
        ms = int(get_settings().flow_media_gap_ms or 100)
    except Exception:
        ms = 100
    return max(0.0, ms / 1000.0)


def _resolve_media_urls(db, step) -> list[str]:
    """Ordered public URLs from media_asset_ids, legacy media_asset_id, then content URL fallback."""
    from app.models.entities import MediaAsset
    from app.services.step_media import parse_media_asset_ids

    ids = parse_media_asset_ids(getattr(step, "media_asset_ids", None), step.media_asset_id)
    urls: list[str] = []
    seen: set[str] = set()
    for aid in ids:
        asset = db.get(MediaAsset, aid)
        url = asset.public_url if asset and asset.public_url else None
        if url and url not in seen:
            urls.append(url)
            seen.add(url)
    if not urls:
        content = (step.content or "").strip()
        if content.startswith(("http://", "https://")):
            urls.append(content)
    return urls


def run_flow_execution(execution_id: str) -> None:
    """
    Sequentially send flow steps via Composio (preferred) or Meta Graph API.
    Never invoked from webhook request path. Manual SEND FLOW only.
    """
    db = SessionLocal()
    try:
        execution = (
            db.query(FlowExecution)
            .options(joinedload(FlowExecution.steps))
            .filter(FlowExecution.id == execution_id)
            .first()
        )
        if not execution:
            return
        if execution.status == ExecutionStatus.CANCELLED:
            return
        if execution.status not in (ExecutionStatus.QUEUED, ExecutionStatus.RUNNING):
            return

        flow = (
            db.query(Flow)
            .options(joinedload(Flow.steps))
            .filter(Flow.id == execution.flow_id)
            .one()
        )
        page = db.query(Page).filter(Page.page_id == execution.page_id).first()
        use_composio = bool(page) and _use_composio(page)
        if not page:
            _fail(db, execution, "Page missing")
            return
        if not use_composio and not page.access_token:
            _fail(db, execution, "Page token missing")
            return

        customer = execution.customer
        if customer is None:
            from app.models.entities import Customer

            customer = db.get(Customer, execution.customer_id)
        if not customer:
            _fail(db, execution, "Customer missing")
            return

        meta_client = None
        composio_client = None
        if use_composio:
            composio_client = ComposioClient()
        else:
            meta_client = MetaClient(access_token=page.access_token)

        steps = sorted(flow.steps, key=lambda s: s.position)
        exec_steps = {s.position: s for s in execution.steps}

        execution.status = ExecutionStatus.RUNNING
        execution.started_at = execution.started_at or datetime.now(timezone.utc)
        db.commit()
        event_bus.publish_sync("execution.running", {"execution_id": execution.id})

        for i, step in enumerate(steps):
            db.refresh(execution)
            if execution.status == ExecutionStatus.CANCELLED:
                return

            estep = exec_steps.get(i)
            if estep:
                estep.status = ExecutionStatus.RUNNING
                estep.started_at = datetime.now(timezone.utc)
                db.commit()

            try:
                if step.step_type == StepType.DELAY:
                    delay = max(0, step.delay_seconds or 0)
                    remaining = delay
                    while remaining > 0:
                        chunk = min(remaining, 1)
                        time.sleep(chunk)
                        remaining -= chunk
                        db.refresh(execution)
                        if execution.status == ExecutionStatus.CANCELLED:
                            return
                    meta_mid = None
                elif step.step_type == StepType.TEXT:
                    text = step.content or ""
                    if use_composio:
                        result = composio_client.send_text(
                            page.page_id, customer.psid, text
                        )
                        meta_mid = extract_message_id(result)
                    else:
                        result = meta_client.send_text(
                            page.page_id, customer.psid, text
                        )
                        meta_mid = result.get("message_id")
                elif step.step_type in (StepType.IMAGE, StepType.AUDIO, StepType.VIDEO):
                    urls = _resolve_media_urls(db, step)
                    if not urls:
                        raise MetaAPIError("Media URL missing for attachment step")
                    att_type = step.step_type.value.lower()
                    gap_s = _media_gap_seconds()
                    meta_mid = None
                    for j, url in enumerate(urls):
                        if j > 0 and gap_s > 0:
                            time.sleep(gap_s)
                        if use_composio:
                            result = composio_client.send_media(
                                page.page_id, customer.psid, att_type, url
                            )
                            meta_mid = extract_message_id(result)
                        else:
                            result = meta_client.send_attachment(
                                page.page_id, customer.psid, att_type, url
                            )
                            meta_mid = result.get("message_id")
                else:
                    raise MetaAPIError(f"Unknown step type {step.step_type}")

                if estep:
                    estep.status = ExecutionStatus.COMPLETED
                    estep.meta_message_id = meta_mid
                    estep.finished_at = datetime.now(timezone.utc)
                execution.current_step_index = i + 1
                db.commit()
                event_bus.publish_sync(
                    "execution.progress",
                    {
                        "execution_id": execution.id,
                        "step_index": i,
                        "status": "COMPLETED",
                    },
                )

                # Honor explicit post-step delay only if > 0. DELAY steps already waited.
                if step.step_type != StepType.DELAY:
                    extra = int(step.delay_seconds or 0)
                    if extra > 0:
                        time.sleep(extra)

            except (MetaAPIError, ComposioAPIError) as exc:
                msg = getattr(exc, "operator_message", None) or str(exc)
                if estep:
                    estep.status = ExecutionStatus.FAILED
                    estep.error_message = msg
                    estep.finished_at = datetime.now(timezone.utc)
                _fail(db, execution, msg)
                return
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                if estep:
                    estep.status = ExecutionStatus.FAILED
                    estep.error_message = msg
                    estep.finished_at = datetime.now(timezone.utc)
                _fail(db, execution, msg)
                return

        execution.status = ExecutionStatus.COMPLETED
        execution.finished_at = datetime.now(timezone.utc)
        db.commit()
        event_bus.publish_sync("execution.completed", {"execution_id": execution.id})
    finally:
        db.close()


def _fail(db, execution: FlowExecution, message: str) -> None:
    execution.status = ExecutionStatus.FAILED
    execution.error_message = message
    execution.finished_at = datetime.now(timezone.utc)
    db.commit()
    event_bus.publish_sync(
        "execution.failed",
        {"execution_id": execution.id, "error": message},
    )
