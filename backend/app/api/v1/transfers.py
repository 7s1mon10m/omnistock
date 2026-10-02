"""Stock transfer endpoints.

Four verbs, four different roles behind them — that split is the feature, not
an accident: 仓管提申请 → 店主审批 → 源仓发出 → 目标仓收货.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.v1.guards import (
    AdminGuard,
    FulfillmentGuard,
    ViewerGuard,
    WarehouseGuard,
)
from app.core.deps import DbSession
from app.models.transfer import TransferStatus
from app.repositories import transfer_repo
from app.schemas.common import Page
from app.schemas.transfer import (
    CancelTransferRequest,
    RejectRequest,
    TransferCreate,
    TransferListRead,
    TransferRead,
    TransferReceiveRequest,
    TransferShipRequest,
)
from app.services import transfer_service

router = APIRouter(prefix="/transfers", tags=["transfers"])


@router.get("", response_model=Page[TransferListRead], summary="调拨单列表")
def list_transfers(
    session: DbSession,
    _: ViewerGuard,
    status: TransferStatus | None = None,
    from_warehouse_id: int | None = None,
    to_warehouse_id: int | None = None,
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Page[TransferListRead]:
    result = transfer_repo.list_transfers(
        session,
        status=status,
        from_warehouse_id=from_warehouse_id,
        to_warehouse_id=to_warehouse_id,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[transfer_service.to_list_read(row) for row in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post("", response_model=TransferRead, status_code=201, summary="发起调拨申请")
def create_transfer(
    payload: TransferCreate, session: DbSession, user: FulfillmentGuard
) -> TransferRead:
    transfer = transfer_service.create_transfer(session, payload, requester_id=user.id)
    return transfer_service.to_read(session, transfer)


@router.get("/{transfer_id}", response_model=TransferRead, summary="调拨单详情")
def get_transfer(transfer_id: int, session: DbSession, _: ViewerGuard) -> TransferRead:
    transfer = transfer_service.get_or_404(session, transfer_id)
    return transfer_service.to_read(session, transfer)


@router.post("/{transfer_id}/approve", response_model=TransferRead, summary="审批通过")
def approve_transfer(transfer_id: int, session: DbSession, user: AdminGuard) -> TransferRead:
    transfer = transfer_service.get_or_404(session, transfer_id)
    transfer = transfer_service.approve(session, transfer, approver_id=user.id)
    return transfer_service.to_read(session, transfer)


@router.post("/{transfer_id}/reject", response_model=TransferRead, summary="审批驳回")
def reject_transfer(
    transfer_id: int, payload: RejectRequest, session: DbSession, user: AdminGuard
) -> TransferRead:
    transfer = transfer_service.get_or_404(session, transfer_id)
    transfer = transfer_service.reject(
        session, transfer, reason=payload.reason, operator_id=user.id
    )
    return transfer_service.to_read(session, transfer)


@router.post(
    "/{transfer_id}/ship", response_model=TransferRead, summary="调出仓发出（进入在途）"
)
def ship_transfer(
    transfer_id: int,
    payload: TransferShipRequest,
    session: DbSession,
    user: WarehouseGuard,
) -> TransferRead:
    transfer = transfer_service.get_or_404(session, transfer_id)
    transfer_service.ship(session, transfer, payload=payload, operator_id=user.id)
    session.refresh(transfer)
    return transfer_service.to_read(session, transfer)


@router.post(
    "/{transfer_id}/receive", response_model=TransferRead, summary="调入仓收货（在途转实际）"
)
def receive_transfer(
    transfer_id: int,
    payload: TransferReceiveRequest,
    session: DbSession,
    user: WarehouseGuard,
) -> TransferRead:
    transfer = transfer_service.get_or_404(session, transfer_id)
    transfer_service.receive(session, transfer, payload=payload, operator_id=user.id)
    session.refresh(transfer)
    return transfer_service.to_read(session, transfer)


@router.post("/{transfer_id}/cancel", response_model=TransferRead, summary="取消调拨（仅未发出）")
def cancel_transfer(
    transfer_id: int,
    payload: CancelTransferRequest,
    session: DbSession,
    user: FulfillmentGuard,
) -> TransferRead:
    transfer = transfer_service.get_or_404(session, transfer_id)
    transfer = transfer_service.cancel(
        session, transfer, reason=payload.reason, operator_id=user.id
    )
    return transfer_service.to_read(session, transfer)
