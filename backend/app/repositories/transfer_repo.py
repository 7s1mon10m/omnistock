"""Stock transfer data access."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.transfer import StockTransfer, StockTransferItem, TransferStatus
from app.utils.pagination import PageResult, paginate


def get(session: Session, transfer_id: int) -> StockTransfer | None:
    return session.get(StockTransfer, transfer_id)


def get_by_no(session: Session, transfer_no: str) -> StockTransfer | None:
    stmt = select(StockTransfer).where(StockTransfer.transfer_no == transfer_no)
    return session.scalar(stmt)


def list_transfers(
    session: Session,
    *,
    status: TransferStatus | None = None,
    from_warehouse_id: int | None = None,
    to_warehouse_id: int | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    stmt = select(StockTransfer)
    if status:
        stmt = stmt.where(StockTransfer.status == status)
    if from_warehouse_id:
        stmt = stmt.where(StockTransfer.from_warehouse_id == from_warehouse_id)
    if to_warehouse_id:
        stmt = stmt.where(StockTransfer.to_warehouse_id == to_warehouse_id)
    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(
            or_(StockTransfer.transfer_no.like(pattern), StockTransfer.reason.like(pattern))
        )
    stmt = stmt.order_by(StockTransfer.id.desc())
    return paginate(session, stmt, page, page_size)


def create(session: Session, **fields) -> StockTransfer:
    transfer = StockTransfer(**fields)
    session.add(transfer)
    session.flush()
    return transfer


def create_item(session: Session, **fields) -> StockTransferItem:
    item = StockTransferItem(**fields)
    session.add(item)
    session.flush()
    return item


def next_no(session: Session, prefix: str, transfer_id: int) -> str:
    return f"{prefix}{transfer_id:08d}"
