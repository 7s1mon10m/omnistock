"""Return orders: intake, QC triage and inbound."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.v1.guards import FulfillmentGuard, ViewerGuard, WarehouseGuard
from app.core.deps import DbSession
from app.models.return_order import ReturnStatus
from app.repositories import return_repo
from app.schemas.common import Page
from app.schemas.return_order import (
    ReturnCancelRequest,
    ReturnInspectRequest,
    ReturnOrderCreate,
    ReturnOrderListRead,
    ReturnOrderRead,
)
from app.services import return_service

router = APIRouter(prefix="/return-orders", tags=["returns"])


@router.get("", response_model=Page[ReturnOrderListRead], summary="退货单列表")
def list_returns(
    session: DbSession,
    _: ViewerGuard,
    status: ReturnStatus | None = None,
    warehouse_id: int | None = None,
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Page[ReturnOrderListRead]:
    result = return_repo.list_returns(
        session,
        status=status,
        warehouse_id=warehouse_id,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[return_service.to_list_read(row) for row in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post(
    "", response_model=ReturnOrderRead, status_code=201, summary="创建退货单（受理）"
)
def create_return(
    payload: ReturnOrderCreate, session: DbSession, user: FulfillmentGuard
) -> ReturnOrderRead:
    return return_service.to_read(
        session, return_service.create(session, payload, operator_id=user.id)
    )


@router.get("/{return_id}", response_model=ReturnOrderRead, summary="退货单详情")
def get_return(return_id: int, session: DbSession, _: ViewerGuard) -> ReturnOrderRead:
    return return_service.to_read(session, return_service.get_or_404(session, return_id))


@router.post(
    "/{return_id}/inspect",
    response_model=ReturnOrderRead,
    summary="质检分流（只记结论，不动库存）",
)
def inspect_return(
    return_id: int,
    payload: ReturnInspectRequest,
    session: DbSession,
    user: WarehouseGuard,
) -> ReturnOrderRead:
    return_order = return_service.get_or_404(session, return_id)
    return return_service.to_read(
        session, return_service.inspect(session, return_order, payload, operator_id=user.id)
    )


@router.post(
    "/{return_id}/inbound", response_model=ReturnOrderRead, summary="退货入库（此时才动库存）"
)
def inbound_return(return_id: int, session: DbSession, user: WarehouseGuard) -> ReturnOrderRead:
    return_order = return_service.get_or_404(session, return_id)
    return return_service.to_read(
        session, return_service.inbound(session, return_order, operator_id=user.id)
    )


@router.post("/{return_id}/cancel", response_model=ReturnOrderRead, summary="取消退货单")
def cancel_return(
    return_id: int, payload: ReturnCancelRequest, session: DbSession, _: FulfillmentGuard
) -> ReturnOrderRead:
    return_order = return_service.get_or_404(session, return_id)
    return return_service.to_read(session, return_service.cancel(session, return_order, payload))
