from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models.entities import Flow, FlowStep, User
from app.schemas.common import (
    FlowCreate,
    FlowExecutionOut,
    FlowOut,
    FlowStepCreate,
    FlowStepOut,
    FlowStepUpdate,
    FlowUpdate,
    SendFlowResponse,
    StepsReorderRequest,
)
from app.security.auth import get_current_user
from app.services.flow_engine import start_flow_execution
from app.services.step_media import apply_media_fields

router = APIRouter(prefix="/api/flows", tags=["flows"])


def _load_flow(db: Session, flow_id: str) -> Flow:
    flow = (
        db.query(Flow)
        .options(joinedload(Flow.steps))
        .filter(Flow.id == flow_id)
        .first()
    )
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    return flow


@router.get("", response_model=list[FlowOut])
def list_flows(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    flows = db.query(Flow).options(joinedload(Flow.steps)).order_by(Flow.created_at.desc()).all()
    return flows


@router.post("", response_model=FlowOut, status_code=201)
def create_flow(
    body: FlowCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    flow = Flow(name=body.name, description=body.description, is_active=body.is_active)
    db.add(flow)
    db.flush()
    for i, s in enumerate(body.steps):
        step = FlowStep(
            flow_id=flow.id,
            position=s.position if s.position is not None else i,
            step_type=s.step_type,
            content=s.content,
            delay_seconds=s.delay_seconds,
        )
        apply_media_fields(
            step,
            media_asset_id=s.media_asset_id,
            media_asset_ids=s.media_asset_ids,
            ids_provided=s.media_asset_ids is not None,
            id_provided=s.media_asset_id is not None,
        )
        db.add(step)
    db.commit()
    return _load_flow(db, flow.id)


@router.get("/{flow_id}", response_model=FlowOut)
def get_flow(flow_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _load_flow(db, flow_id)


@router.patch("/{flow_id}", response_model=FlowOut)
def update_flow(
    flow_id: str,
    body: FlowUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    flow = _load_flow(db, flow_id)
    if body.name is not None:
        flow.name = body.name
    if body.description is not None:
        flow.description = body.description
    if body.is_active is not None:
        flow.is_active = body.is_active
    db.commit()
    return _load_flow(db, flow_id)


@router.delete("/{flow_id}", status_code=204)
def delete_flow(flow_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    flow = _load_flow(db, flow_id)
    db.delete(flow)
    db.commit()


@router.post("/{flow_id}/steps", response_model=FlowStepOut, status_code=201)
def add_step(
    flow_id: str,
    body: FlowStepCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    flow = _load_flow(db, flow_id)
    pos = body.position if body.position is not None else len(flow.steps)
    step = FlowStep(
        flow_id=flow.id,
        position=pos,
        step_type=body.step_type,
        content=body.content,
        delay_seconds=body.delay_seconds,
    )
    apply_media_fields(
        step,
        media_asset_id=body.media_asset_id,
        media_asset_ids=body.media_asset_ids,
        ids_provided=body.media_asset_ids is not None,
        id_provided=body.media_asset_id is not None,
    )
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


@router.patch("/{flow_id}/steps/{step_id}", response_model=FlowStepOut)
def update_step(
    flow_id: str,
    step_id: str,
    body: FlowStepUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    step = db.query(FlowStep).filter(FlowStep.id == step_id, FlowStep.flow_id == flow_id).first()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    data = body.model_dump(exclude_unset=True)
    for field in ("step_type", "content", "delay_seconds", "position"):
        if field in data:
            setattr(step, field, data[field])
    if "media_asset_ids" in data or "media_asset_id" in data:
        apply_media_fields(
            step,
            media_asset_id=data.get("media_asset_id"),
            media_asset_ids=data.get("media_asset_ids"),
            ids_provided="media_asset_ids" in data,
            id_provided="media_asset_id" in data,
        )
    db.commit()
    db.refresh(step)
    return step


@router.delete("/{flow_id}/steps/{step_id}", status_code=204)
def delete_step(
    flow_id: str,
    step_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    step = db.query(FlowStep).filter(FlowStep.id == step_id, FlowStep.flow_id == flow_id).first()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    db.delete(step)
    db.commit()


@router.post("/{flow_id}/steps/reorder", response_model=FlowOut)
def reorder_steps(
    flow_id: str,
    body: StepsReorderRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    flow = _load_flow(db, flow_id)
    by_id = {s.id: s for s in flow.steps}
    if set(body.step_ids) != set(by_id.keys()):
        raise HTTPException(status_code=400, detail="step_ids must match all flow steps")
    for i, sid in enumerate(body.step_ids):
        by_id[sid].position = i
    db.commit()
    return _load_flow(db, flow_id)


@router.post("/{flow_id}/duplicate", response_model=FlowOut, status_code=201)
def duplicate_flow(
    flow_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    src = _load_flow(db, flow_id)
    copy = Flow(name=f"{src.name} (copy)", description=src.description, is_active=src.is_active)
    db.add(copy)
    db.flush()
    for s in sorted(src.steps, key=lambda x: x.position):
        db.add(
            FlowStep(
                flow_id=copy.id,
                position=s.position,
                step_type=s.step_type,
                content=s.content,
                media_asset_id=s.media_asset_id,
                media_asset_ids=s.media_asset_ids,
                delay_seconds=s.delay_seconds,
            )
        )
    db.commit()
    return _load_flow(db, copy.id)


@router.post("/{flow_id}/customers/{customer_id}/send", response_model=SendFlowResponse)
def send_flow(
    flow_id: str,
    customer_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Only authenticated POST starts sending. Webhook never calls this."""
    execution = start_flow_execution(
        db,
        flow_id=flow_id,
        customer_id=customer_id,
        user_id=user.id,
        idempotency_key=idempotency_key,
    )
    return SendFlowResponse(execution=FlowExecutionOut.model_validate(execution), queued=True)
