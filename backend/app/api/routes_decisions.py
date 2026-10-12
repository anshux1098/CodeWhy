from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_source
from app.schemas.decisions import DecisionDetail
from app.schemas.errors import ErrorResponse
from app.services.data_source import DataSource

router = APIRouter(tags=["decisions"])


@router.get(
    "/decisions/{decision_id}",
    response_model=DecisionDetail,
    responses={404: {"model": ErrorResponse}},
    summary="One decision with its citations",
)
def get_decision(decision_id: str, source: DataSource = Depends(get_source)) -> DecisionDetail:
    return source.get_decision(decision_id)
