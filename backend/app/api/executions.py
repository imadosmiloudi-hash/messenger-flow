from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models.entities import FlowExecution, User
from app.schemas.common import FlowExecutionOut
from app.security.auth import get_current_user
from app.services.flow_engine import cancel_execution, retry_execution

router = APIRouter(prefix="/api/executions", tags=["executions"])


@router.get("/{execution_id}", response_model=FlowExecutionOut)
def get_execution(
    execution_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    execution = (
        db.query(FlowExecution)
        .options(joinedload(FlowExecution.steps))
        .filter(FlowExecution.id == execution_id)
        .first()
    )
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution


@router.post("/{execution_id}/cancel", response_model=FlowExecutionOut)
def cancel(
    execution_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return cancel_execution(db, execution_id, user.id)


@router.post("/{execution_id}/retry", response_model=FlowExecutionOut)
def retry(
    execution_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return retry_execution(db, execution_id, user.id)
