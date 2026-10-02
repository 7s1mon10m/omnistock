"""退货单与质检分流。

退货分两步，顺序不能颠倒：

1. **质检**（inspect）—— 只是记录「这批货分别该去哪」，**不动库存**；
2. **入库**（inbound）—— 按质检结论一次性把四条流水写下去。

分开是因为质检结论常常要改：第一眼看是次品，复核后觉得还能卖。如果质检
当场就改了库存，改结论就得先做一笔反向流水，账会立刻变脏。

四种结论对应四个去处：

* 可再售 → ``return_inbound``，回到可售库存；
* 次品   → ``return_defective``，进次品区（``qty_delta`` 为 0）；
* 维修   → ``return_repair``，进维修区（``qty_delta`` 为 0）；
* 报损   → ``damage_scrap``，直接出账。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import (
    RETURN_ITEM_NOT_FOUND,
    RETURN_ORDER_NOT_FOUND,
    RETURN_QTY_EXCEEDED,
    RETURN_QTY_INVALID,
    SKU_NOT_FOUND,
    WAREHOUSE_NOT_FOUND,
    BusinessError,
)
from app.domain import return_state_machine
from app.models.base import utcnow
from app.models.inventory import InventoryTransactionType
from app.models.return_order import ReturnOrder, ReturnOrderItem, ReturnStatus
from app.repositories import product_repo, return_repo, warehouse_repo
from app.schemas.return_order import (
    ReturnCancelRequest,
    ReturnInspectRequest,
    ReturnItemRead,
    ReturnOrderCreate,
    ReturnOrderListRead,
    ReturnOrderRead,
)
from app.services import inventory_service

LEDGER_REF = "return_order"


def get_or_404(session: Session, return_id: int) -> ReturnOrder:
    return_order = return_repo.get(session, return_id)
    if return_order is None:
        raise BusinessError(RETURN_ORDER_NOT_FOUND, http_status=404)
    return return_order


def _user_name(session: Session, user_id: int | None) -> str:
    from app.repositories import user_repo

    if not user_id:
        return ""
    user = user_repo.get(session, user_id)
    return (user.full_name or user.username) if user else ""


def _item_or_404(return_order: ReturnOrder, item_id: int) -> ReturnOrderItem:
    item = next((row for row in return_order.items if row.id == item_id), None)
    if item is None:
        raise BusinessError(
            RETURN_ITEM_NOT_FOUND, detail={"return_item_id": item_id}, http_status=404
        )
    return item


# --------------------------------------------------------------------- create
def _sold_snapshot(session: Session, payload: ReturnOrderCreate) -> dict[int, int]:
    """原订单里每个 SKU 的可退基准。

    给不出 order_id 时（例如只有平台单号）就没有基准，此时不校验数量 ——
    宁可放行也不用一个错的数字去拦截真实退货。
    """
    if not payload.order_id:
        return {}
    return return_repo.count_shipped_by_sku(session, payload.order_id)


def create(
    session: Session,
    payload: ReturnOrderCreate,
    *,
    operator_id: int | None = None,
) -> ReturnOrder:
    if warehouse_repo.get(session, payload.warehouse_id) is None:
        raise BusinessError(WAREHOUSE_NOT_FOUND, http_status=404)
    if payload.order_id is None and not payload.channel_order_no:
        raise BusinessError(
            RETURN_ORDER_NOT_FOUND, "必须关联原订单或填写渠道单号", http_status=400
        )
    for item in payload.items:
        if product_repo.get_sku(session, item.sku_id) is None:
            raise BusinessError(SKU_NOT_FOUND, detail={"sku_id": item.sku_id}, http_status=404)

    sold_map = _sold_snapshot(session, payload)
    already = (
        return_repo.sum_returned_by_sku(session, payload.order_id)
        if payload.order_id
        else {}
    )

    merged: dict[int, int] = {}
    for item in payload.items:
        merged[item.sku_id] = merged.get(item.sku_id, 0) + item.quantity

    for sku_id, quantity in merged.items():
        sold = sold_map.get(sku_id)
        if sold is None:
            continue
        returnable = max(0, sold - already.get(sku_id, 0))
        if quantity > returnable:
            sku = product_repo.get_sku(session, sku_id)
            raise BusinessError(
                RETURN_QTY_EXCEEDED,
                f"本次退 {quantity} 件，但该商品最多还能退 {returnable} 件"
                f"（已售 {sold}、已退 {already.get(sku_id, 0)}）",
                detail={
                    "sku_id": sku_id,
                    "sku_code": sku.sku_code if sku else "",
                    "sold": sold,
                    "already_returned": already.get(sku_id, 0),
                    "returnable": returnable,
                    "requested": quantity,
                },
                http_status=409,
            )

    return_order = return_repo.create(
        session,
        return_no="",
        order_id=payload.order_id,
        channel_id=payload.channel_id,
        channel_order_no=payload.channel_order_no,
        buyer_nick=payload.buyer_nick,
        warehouse_id=payload.warehouse_id,
        status=ReturnStatus.PENDING,
        reason=payload.reason,
        created_by=operator_id,
        remark=payload.remark,
    )
    return_order.return_no = f"{settings.RETURN_CODE_PREFIX}{return_order.id:08d}"

    for line_no, item in enumerate(payload.items, start=1):
        return_repo.create_item(
            session,
            return_id=return_order.id,
            line_no=line_no,
            sku_id=item.sku_id,
            quantity=item.quantity,
            sold_qty=sold_map.get(item.sku_id, 0),
            remark=item.remark,
        )

    session.commit()
    session.refresh(return_order)
    return return_order


# ------------------------------------------------------------------- inspect
def inspect(
    session: Session,
    return_order: ReturnOrder,
    payload: ReturnInspectRequest,
    *,
    operator_id: int | None = None,
) -> ReturnOrder:
    """记录质检结论。**此时不动库存。**"""
    # 先把数据本身校验干净，再判断状态 —— 否则「已质检的单子重复提交」
    # 会盖掉「分流数量填错了」这个更有用的提示。
    updates: dict[int, ReturnOrderItem] = {}
    for line in payload.items:
        item = _item_or_404(return_order, line.return_item_id)
        total = (
            line.resellable_qty + line.defective_qty + line.repair_qty + line.scrap_qty
        )
        if total != item.quantity:
            raise BusinessError(
                RETURN_QTY_INVALID,
                f"{item.sku.sku_code if item.sku else item.sku_id} 的分流合计 {total}，"
                f"与退货量 {item.quantity} 不符",
                detail={"return_item_id": item.id, "total": total, "quantity": item.quantity},
                http_status=400,
            )
        updates[item.id] = item

    missing = [row.id for row in return_order.items if row.id not in updates]
    if missing:
        raise BusinessError(
            RETURN_QTY_INVALID,
            f"还有 {len(missing)} 行未质检",
            detail={"return_item_ids": missing},
            http_status=400,
        )

    return_state_machine.require(return_order.status, ReturnStatus.INSPECTED)

    for line in payload.items:
        item = updates[line.return_item_id]
        item.disposition = line.disposition
        item.resellable_qty = line.resellable_qty
        item.defective_qty = line.defective_qty
        item.repair_qty = line.repair_qty
        item.scrap_qty = line.scrap_qty
        if line.remark:
            item.remark = line.remark

    # 必须每一行都给了结论，否则入库时会漏掉一部分货。
    missing = [row.id for row in return_order.items if row.id not in updates]
    if missing:
        raise BusinessError(
            RETURN_QTY_INVALID,
            f"还有 {len(missing)} 行未质检",
            detail={"return_item_ids": missing},
            http_status=400,
        )

    return_order.status = ReturnStatus.INSPECTED
    return_order.inspected_by = operator_id
    return_order.inspected_at = utcnow()
    if payload.remark:
        return_order.remark = f"{return_order.remark} | {payload.remark}"[:255]
    session.commit()
    return return_order


# ------------------------------------------------------------------- inbound
def inbound(
    session: Session, return_order: ReturnOrder, *, operator_id: int | None = None
) -> ReturnOrder:
    """按质检结论落账。这一刻库存才真的变。"""
    return_state_machine.require(return_order.status, ReturnStatus.INBOUND)

    for item in return_order.items:
        inventory_service.return_inbound(
            session,
            sku_id=item.sku_id,
            warehouse_id=return_order.warehouse_id,
            resellable_qty=item.resellable_qty,
            defective_qty=item.defective_qty,
            repair_qty=item.repair_qty,
            scrap_qty=item.scrap_qty if settings.DAMAGE_AUTO_SCRAP else 0,
            ref_id=return_order.id,
            operator_id=operator_id,
            remark=f"退货入库 {return_order.return_no}",
            idempotency_key=f"return:{return_order.id}:{item.id}",
        )

    return_order.status = ReturnStatus.INBOUND
    return_order.inbound_by = operator_id
    return_order.inbound_at = utcnow()
    session.commit()
    return return_order


def cancel(
    session: Session, return_order: ReturnOrder, payload: ReturnCancelRequest
) -> ReturnOrder:
    return_state_machine.require(return_order.status, ReturnStatus.CANCELLED)
    return_order.status = ReturnStatus.CANCELLED
    if payload.reason:
        return_order.remark = f"{return_order.remark} | 取消：{payload.reason}"[:255]
    session.commit()
    return return_order


# ----------------------------------------------------------------- read views
def to_item_read(session: Session, item: ReturnOrderItem) -> ReturnItemRead:
    already = (
        return_repo.sum_returned_by_sku(session, item.return_order.order_id)
        if item.return_order and item.return_order.order_id
        else {}
    )
    returnable = max(0, item.sold_qty - already.get(item.sku_id, 0))
    return ReturnItemRead(
        id=item.id,
        line_no=item.line_no,
        sku_id=item.sku_id,
        sku_code=item.sku.sku_code if item.sku else "",
        sku_name=item.sku.display_name if item.sku else "",
        quantity=item.quantity,
        sold_qty=item.sold_qty,
        returnable_qty=returnable,
        already_returned_qty=already.get(item.sku_id, 0),
        disposition=item.disposition,
        resellable_qty=item.resellable_qty,
        defective_qty=item.defective_qty,
        repair_qty=item.repair_qty,
        scrap_qty=item.scrap_qty,
        inspected_total=item.inspected_total,
        remark=item.remark,
    )


def to_read(session: Session, return_order: ReturnOrder) -> ReturnOrderRead:
    return ReturnOrderRead(
        id=return_order.id,
        return_no=return_order.return_no,
        order_id=return_order.order_id,
        channel_id=return_order.channel_id,
        channel_name=return_order.channel.name if return_order.channel else "",
        channel_order_no=return_order.channel_order_no,
        buyer_nick=return_order.buyer_nick,
        warehouse_id=return_order.warehouse_id,
        warehouse_code=return_order.warehouse.code if return_order.warehouse else "",
        warehouse_name=return_order.warehouse.name if return_order.warehouse else "",
        status=return_order.status,
        reason=return_order.reason,
        created_by=return_order.created_by,
        created_by_name=_user_name(session, return_order.created_by),
        inspected_by=return_order.inspected_by,
        inspected_by_name=_user_name(session, return_order.inspected_by),
        inspected_at=return_order.inspected_at,
        inbound_by=return_order.inbound_by,
        inbound_by_name=_user_name(session, return_order.inbound_by),
        inbound_at=return_order.inbound_at,
        total_quantity=return_order.total_quantity,
        remark=return_order.remark,
        items=[
            to_item_read(session, item)
            for item in sorted(return_order.items, key=lambda r: r.line_no)
        ],
        created_at=return_order.created_at,
    )


def to_list_read(return_order: ReturnOrder) -> ReturnOrderListRead:
    return ReturnOrderListRead(
        id=return_order.id,
        return_no=return_order.return_no,
        channel_order_no=return_order.channel_order_no,
        buyer_nick=return_order.buyer_nick,
        warehouse_name=return_order.warehouse.name if return_order.warehouse else "",
        status=return_order.status,
        reason=return_order.reason,
        total_quantity=return_order.total_quantity,
        created_at=return_order.created_at,
    )
