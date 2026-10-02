"""多仓库调拨服务。

流程刻意分成四步，因为每一步的责任人不同：仓管提申请、店主审批、源仓发货、
目标仓收货。把审批夹在中间是有价值的 —— 调拨往往是「这边缺货从那边的货里
挪」，没有审批就很容易把旺销仓的货挪空。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import (
    TRANSFER_ITEM_NOT_FOUND,
    TRANSFER_NOT_FOUND,
    TRANSFER_NO_ITEMS,
    TRANSFER_QUANTITY_EXCEEDS,
    TRANSFER_QUANTITY_INVALID,
    TRANSFER_SAME_WAREHOUSE,
    TRANSFER_STATUS_INVALID,
    TRANSFER_STOCK_SHORTAGE,
    SKU_NOT_FOUND,
    WAREHOUSE_NOT_FOUND,
    BusinessError,
)
from app.models.base import utcnow
from app.models.product import Sku
from app.models.transfer import StockTransfer, StockTransferItem, TransferStatus
from app.repositories import product_repo, transfer_repo, user_repo, warehouse_repo
from app.schemas.transfer import (
    TransferCreate,
    TransferListRead,
    TransferRead,
    TransferItemRead,
)
from app.services import inventory_service

LEDGER_REF = "stock_transfer"


def get_or_404(session: Session, transfer_id: int) -> StockTransfer:
    transfer = transfer_repo.get(session, transfer_id)
    if transfer is None:
        raise BusinessError(TRANSFER_NOT_FOUND, http_status=404)
    return transfer


def _user_name(session: Session, user_id: int | None) -> str:
    if not user_id:
        return ""
    user = user_repo.get(session, user_id)
    return (user.full_name or user.username) if user else ""


def _item_or_404(transfer: StockTransfer, item_id: int) -> StockTransferItem:
    item = next((row for row in transfer.items if row.id == item_id), None)
    if item is None:
        raise BusinessError(
            TRANSFER_ITEM_NOT_FOUND, detail={"transfer_item_id": item_id}, http_status=404
        )
    return item


# --------------------------------------------------------------------- create
def create_transfer(
    session: Session, payload: TransferCreate, *, requester_id: int | None = None
) -> StockTransfer:
    if payload.from_warehouse_id == payload.to_warehouse_id:
        raise BusinessError(TRANSFER_SAME_WAREHOUSE, http_status=409)
    if warehouse_repo.get(session, payload.from_warehouse_id) is None:
        raise BusinessError(WAREHOUSE_NOT_FOUND, http_status=404)
    if warehouse_repo.get(session, payload.to_warehouse_id) is None:
        raise BusinessError(WAREHOUSE_NOT_FOUND, http_status=404)
    if not payload.items:
        raise BusinessError(TRANSFER_NO_ITEMS, http_status=400)

    # 关闭审批时直接进入「已批准，待发出」，省掉一道手工动作。
    initial = (
        TransferStatus.PENDING
        if settings.TRANSFER_REQUIRE_APPROVAL
        else TransferStatus.APPROVED
    )

    transfer = transfer_repo.create(
        session,
        from_warehouse_id=payload.from_warehouse_id,
        to_warehouse_id=payload.to_warehouse_id,
        status=initial,
        reason=payload.reason,
        remark=payload.remark,
        requested_by=requester_id,
        requested_at=utcnow(),
        approved_by=None if settings.TRANSFER_REQUIRE_APPROVAL else requester_id,
        approved_at=None if settings.TRANSFER_REQUIRE_APPROVAL else utcnow(),
    )
    transfer.transfer_no = transfer_repo.next_no(
        session, settings.TRANSFER_CODE_PREFIX, transfer.id
    )

    for line_no, item in enumerate(payload.items, start=1):
        if product_repo.get_sku(session, item.sku_id) is None:
            raise BusinessError(SKU_NOT_FOUND, detail={"sku_id": item.sku_id}, http_status=404)
        transfer_repo.create_item(
            session,
            transfer_id=transfer.id,
            line_no=line_no,
            sku_id=item.sku_id,
            quantity=item.quantity,
            remark=item.remark,
        )

    session.commit()
    session.refresh(transfer)
    return transfer


# ------------------------------------------------------------------ approval
def approve(
    session: Session, transfer: StockTransfer, *, approver_id: int | None = None
) -> StockTransfer:
    if transfer.status != TransferStatus.PENDING:
        raise BusinessError(
            TRANSFER_STATUS_INVALID,
            f"当前状态 {transfer.status.value} 不能审批",
            http_status=409,
        )
    transfer.status = TransferStatus.APPROVED
    transfer.approved_by = approver_id
    transfer.approved_at = utcnow()
    session.commit()
    return transfer


def reject(
    session: Session, transfer: StockTransfer, *, reason: str, operator_id: int | None = None
) -> StockTransfer:
    if transfer.status != TransferStatus.PENDING:
        raise BusinessError(
            TRANSFER_STATUS_INVALID,
            f"当前状态 {transfer.status.value} 不能驳回",
            http_status=409,
        )
    transfer.status = TransferStatus.REJECTED
    transfer.approved_by = operator_id
    transfer.approved_at = utcnow()
    transfer.reject_reason = reason
    session.commit()
    return transfer


# ---------------------------------------------------------------------- ship
def ship(
    session: Session,
    transfer: StockTransfer,
    *,
    payload=None,
    operator_id: int | None = None,
) -> list[tuple[int, int, int, int]]:
    """源仓发出：实际库存减少，调入仓在途增加。

    Returns ``[(sku_id, from_wh, to_wh, qty), ...]``.
    """
    if transfer.status != TransferStatus.APPROVED:
        raise BusinessError(
            TRANSFER_STATUS_INVALID,
            f"当前状态 {transfer.status.value} 不能发出",
            http_status=409,
        )

    requested: dict[int, int] = {}
    if payload is not None and payload.items:
        for line in payload.items:
            item = _item_or_404(transfer, line.transfer_item_id)
            requested[item.id] = line.quantity if line.quantity is not None else item.quantity

    # 先校验再写账：任何一行不够就整单不发，避免发出半张单。
    planned: list[tuple[StockTransferItem, int]] = []
    for item in transfer.items:
        qty = requested.get(item.id, item.quantity)
        if qty <= 0:
            raise BusinessError(TRANSFER_QUANTITY_INVALID, http_status=400)
        if qty > item.quantity:
            raise BusinessError(
                TRANSFER_QUANTITY_EXCEEDS,
                f"申请 {item.quantity} 件，不能发出 {qty} 件",
                detail={"transfer_item_id": item.id, "requested": item.quantity},
                http_status=409,
            )
        planned.append((item, qty))

    shortages: list[dict] = []
    for item, qty in planned:
        available = inventory_service.available_for(
            session, item.sku_id, transfer.from_warehouse_id
        )
        if available < qty:
            sku: Sku | None = product_repo.get_sku(session, item.sku_id)
            shortages.append(
                {
                    "transfer_item_id": item.id,
                    "sku_id": item.sku_id,
                    "sku_code": sku.sku_code if sku else "",
                    "required": qty,
                    "available": available,
                }
            )
    if shortages:
        raise BusinessError(
            TRANSFER_STOCK_SHORTAGE,
            detail={"from_warehouse_id": transfer.from_warehouse_id, "shortages": shortages},
            http_status=409,
        )

    shipped: list[tuple[int, int, int, int]] = []
    for item, qty in planned:
        inventory_service.transfer_ship(
            session,
            sku_id=item.sku_id,
            from_warehouse_id=transfer.from_warehouse_id,
            to_warehouse_id=transfer.to_warehouse_id,
            quantity=qty,
            ref_id=transfer.id,
            operator_id=operator_id,
            remark=f"调拨发出 {transfer.transfer_no}",
            idempotency_key=f"transfer-ship:{transfer.id}:{item.id}",
        )
        item.shipped_qty = qty
        shipped.append((item.sku_id, transfer.from_warehouse_id, transfer.to_warehouse_id, qty))

    transfer.status = TransferStatus.IN_TRANSIT
    transfer.shipped_by = operator_id
    transfer.shipped_at = utcnow()
    if payload is not None and payload.remark:
        transfer.remark = f"{transfer.remark} | {payload.remark}"[:255]
    session.commit()
    return shipped


# ------------------------------------------------------------------- receive
def receive(
    session: Session,
    transfer: StockTransfer,
    *,
    payload=None,
    operator_id: int | None = None,
) -> list[tuple[int, int, int]]:
    """调入仓收货：在途转为实际，次品单独入次品区。

    Returns ``[(sku_id, qualified_qty, defective_qty), ...]``.
    """
    if transfer.status != TransferStatus.IN_TRANSIT:
        raise BusinessError(
            TRANSFER_STATUS_INVALID,
            f"当前状态 {transfer.status.value} 不能收货",
            http_status=409,
        )

    overrides: dict[int, tuple[int, int]] = {}
    if payload is not None and payload.items:
        for line in payload.items:
            item = _item_or_404(transfer, line.transfer_item_id)
            qty = line.quantity if line.quantity is not None else item.shipped_qty - item.received_qty
            overrides[item.id] = (qty, line.defective_qty)

    planned: list[tuple[StockTransferItem, int, int]] = []
    for item in transfer.items:
        outstanding = item.shipped_qty - item.received_qty
        if outstanding <= 0:
            continue
        qty, defective = overrides.get(item.id, (outstanding, 0))
        if qty <= 0 or qty > outstanding or defective < 0 or defective > qty:
            raise BusinessError(
                TRANSFER_QUANTITY_INVALID,
                f"本次实收 {qty} 件不合法（最多可收 {outstanding} 件，次品不能多于实收）",
                detail={"transfer_item_id": item.id, "outstanding": outstanding},
                http_status=400,
            )
        planned.append((item, qty, defective))

    if not planned:
        raise BusinessError(TRANSFER_QUANTITY_INVALID, "没有待收货的行", http_status=400)

    received: list[tuple[int, int, int]] = []
    for item, qty, defective in planned:
        inventory_service.transfer_receive(
            session,
            sku_id=item.sku_id,
            to_warehouse_id=transfer.to_warehouse_id,
            quantity=qty,
            defective_qty=defective,
            ref_id=transfer.id,
            operator_id=operator_id,
            remark=f"调拨收货 {transfer.transfer_no}",
            idempotency_key=f"transfer-recv:{transfer.id}:{item.id}:{item.received_qty}",
        )
        item.received_qty += qty
        item.defective_qty += defective
        received.append((item.sku_id, qty - defective, defective))

    # 全部收齐才结单；没收完就继续挂着「在途」，剩余部分仍可再收。
    if all(row.received_qty >= row.shipped_qty for row in transfer.items):
        transfer.status = TransferStatus.RECEIVED
        transfer.received_by = operator_id
        transfer.received_at = utcnow()
    if payload is not None and payload.remark:
        transfer.remark = f"{transfer.remark} | {payload.remark}"[:255]

    session.commit()
    return received


def cancel(
    session: Session,
    transfer: StockTransfer,
    *,
    reason: str = "",
    operator_id: int | None = None,
) -> StockTransfer:
    """只允许在「尚未发出」的阶段取消 —— 货一旦上路就必须走完收货。"""
    if transfer.status not in (TransferStatus.PENDING, TransferStatus.APPROVED):
        raise BusinessError(
            TRANSFER_STATUS_INVALID,
            f"当前状态 {transfer.status.value} 不能取消；已发出的调拨必须完成收货",
            http_status=409,
        )
    transfer.status = TransferStatus.CANCELLED
    transfer.cancelled_at = utcnow()
    if reason:
        transfer.remark = f"{transfer.remark} | 取消：{reason}"[:255]
    session.commit()
    return transfer


# ----------------------------------------------------------------- read views
def to_item_read(item: StockTransferItem) -> TransferItemRead:
    sku = item.sku
    return TransferItemRead(
        id=item.id,
        line_no=item.line_no,
        sku_id=item.sku_id,
        sku_code=sku.sku_code if sku else "",
        sku_name=sku.display_name if sku else "",
        quantity=item.quantity,
        shipped_qty=item.shipped_qty,
        received_qty=item.received_qty,
        defective_qty=item.defective_qty,
        qualified_qty=item.qualified_qty,
        remark=item.remark,
    )


def to_read(session: Session, transfer: StockTransfer) -> TransferRead:
    from_wh = transfer.from_warehouse
    to_wh = transfer.to_warehouse
    return TransferRead(
        id=transfer.id,
        transfer_no=transfer.transfer_no,
        from_warehouse_id=transfer.from_warehouse_id,
        from_warehouse_code=from_wh.code if from_wh else "",
        from_warehouse_name=from_wh.name if from_wh else "",
        to_warehouse_id=transfer.to_warehouse_id,
        to_warehouse_code=to_wh.code if to_wh else "",
        to_warehouse_name=to_wh.name if to_wh else "",
        status=transfer.status,
        reason=transfer.reason,
        remark=transfer.remark,
        requested_by=transfer.requested_by,
        requested_by_name=_user_name(session, transfer.requested_by),
        requested_at=transfer.requested_at,
        approved_by=transfer.approved_by,
        approved_by_name=_user_name(session, transfer.approved_by),
        approved_at=transfer.approved_at,
        reject_reason=transfer.reject_reason,
        shipped_by=transfer.shipped_by,
        shipped_by_name=_user_name(session, transfer.shipped_by),
        shipped_at=transfer.shipped_at,
        received_by=transfer.received_by,
        received_by_name=_user_name(session, transfer.received_by),
        received_at=transfer.received_at,
        total_quantity=transfer.total_quantity,
        shipped_quantity=transfer.shipped_quantity,
        received_quantity=transfer.received_quantity,
        items=[to_item_read(item) for item in sorted(transfer.items, key=lambda r: r.line_no)],
        created_at=transfer.created_at,
    )


def to_list_read(transfer: StockTransfer) -> TransferListRead:
    from_wh = transfer.from_warehouse
    to_wh = transfer.to_warehouse
    return TransferListRead(
        id=transfer.id,
        transfer_no=transfer.transfer_no,
        from_warehouse_code=from_wh.code if from_wh else "",
        to_warehouse_code=to_wh.code if to_wh else "",
        status=transfer.status,
        reason=transfer.reason,
        total_quantity=transfer.total_quantity,
        shipped_quantity=transfer.shipped_quantity,
        received_quantity=transfer.received_quantity,
        created_at=transfer.created_at,
    )
