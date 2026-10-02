"""Replenishment suggestions.

The whole feature is one formula (see :mod:`app.domain.replenish_formula`) plus
the plumbing to act on it.  What makes it more than a spreadsheet is the
**dedup_key**: a suggestion stays ``open`` until someone converts or dismisses
it, so re-running the scan tomorrow does not produce a second copy of the same
"buy 40 more" line.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import (
    PURCHASE_ORDER_STATUS_INVALID,
    REPLENISH_SUGGESTION_NOT_FOUND,
    BusinessError,
)
from app.domain import replenish_formula
from app.models.alert import ReplenishmentSuggestion, SuggestionStatus
from app.models.base import utcnow
from app.models.inventory import InventoryStock
from app.repositories import alert_repo, product_repo
from app.schemas.alert import SuggestionRead, SuggestionToPurchaseOrder
from app.schemas.purchase import PurchaseOrderCreate, PurchaseOrderItemIn
from app.services import forecast_service, purchase_service


def generate(
    session: Session,
    *,
    warehouse_id: int | None = None,
    sku_id: int | None = None,
    limit: int | None = None,
) -> list[ReplenishmentSuggestion]:
    """Recompute suggestions for every stock row with a safety stock set."""
    stmt = select(InventoryStock).where(InventoryStock.safety_qty > 0)
    if warehouse_id is not None:
        stmt = stmt.where(InventoryStock.warehouse_id == warehouse_id)
    if sku_id is not None:
        stmt = stmt.where(InventoryStock.sku_id == sku_id)
    rows = list(session.scalars(stmt))
    if limit:
        rows = rows[:limit]

    created: list[ReplenishmentSuggestion] = []
    for stock in rows:
        stats = forecast_service.forecast_for_sku(session, stock.sku_id)
        suggested = replenish_formula.suggested_quantity(
            forecast_qty=int(stats["forecast_qty"]),
            safety_qty=stock.safety_qty,
            available_qty=stock.available_qty,
            in_transit_qty=stock.in_transit_qty,
        )
        if suggested <= 0:
            continue

        dedup = f"{stock.sku_id}:{stock.warehouse_id}"
        if alert_repo.get_suggestion_by_dedup(session, dedup) is not None:
            continue

        suggestion = alert_repo.create_suggestion(
            session,
            suggestion_no="",
            sku_id=stock.sku_id,
            warehouse_id=stock.warehouse_id,
            supplier_id=stock.sku.default_supplier_id if stock.sku else None,
            avg_daily_sales=stats["avg_daily_sales"],
            forecast_qty=int(stats["forecast_qty"]),
            safety_qty=stock.safety_qty,
            available_qty=stock.available_qty,
            in_transit_qty=stock.in_transit_qty,
            suggested_qty=suggested,
            status=SuggestionStatus.OPEN,
            generated_at=utcnow(),
            dedup_key=dedup,
        )
        suggestion.suggestion_no = (
            f"RP{suggestion.id:08d}"
        )
        created.append(suggestion)

    session.commit()
    return created


def to_read(suggestion: ReplenishmentSuggestion) -> SuggestionRead:
    sku = suggestion.sku
    return SuggestionRead(
        id=suggestion.id,
        suggestion_no=suggestion.suggestion_no,
        sku_id=suggestion.sku_id,
        sku_code=sku.sku_code if sku else "",
        sku_name=sku.display_name if sku else "",
        warehouse_id=suggestion.warehouse_id,
        warehouse_code=suggestion.warehouse.code if suggestion.warehouse else "",
        warehouse_name=suggestion.warehouse.name if suggestion.warehouse else "",
        supplier_id=suggestion.supplier_id,
        supplier_name=suggestion.supplier.name if suggestion.supplier else "",
        avg_daily_sales=suggestion.avg_daily_sales,
        forecast_qty=suggestion.forecast_qty,
        safety_qty=suggestion.safety_qty,
        available_qty=suggestion.available_qty,
        in_transit_qty=suggestion.in_transit_qty,
        suggested_qty=suggestion.suggested_qty,
        status=suggestion.status,
        purchase_order_id=suggestion.purchase_order_id,
        generated_at=suggestion.generated_at,
        converted_at=suggestion.converted_at,
        remark=suggestion.remark,
        created_at=suggestion.created_at,
    )


def get_or_404(session: Session, suggestion_id: int) -> ReplenishmentSuggestion:
    suggestion = alert_repo.get_suggestion(session, suggestion_id)
    if suggestion is None:
        raise BusinessError(REPLENISH_SUGGESTION_NOT_FOUND, http_status=404)
    return suggestion


def dismiss(session: Session, suggestion_id: int, *, remark: str = "") -> ReplenishmentSuggestion:
    """忽略这条建议 —— 释放 dedup_key，下一轮可以重新评估。"""
    suggestion = get_or_404(session, suggestion_id)
    if suggestion.status != SuggestionStatus.OPEN:
        raise BusinessError(
            PURCHASE_ORDER_STATUS_INVALID,
            f"当前状态 {suggestion.status.value} 不能忽略",
            http_status=409,
        )
    suggestion.status = SuggestionStatus.DISMISSED
    suggestion.dedup_key = None
    if remark:
        suggestion.remark = remark[:255]
    session.commit()
    return suggestion


def to_purchase_order(
    session: Session,
    suggestion_id: int,
    payload: SuggestionToPurchaseOrder,
    *,
    operator_id: int | None = None,
):
    """Turn a suggestion into a draft purchase order.

    Deliberately creates a **draft**, not a submitted order: a suggestion is a
    number, not a commitment.  Whoever owns buying still has to press 下单.
    """
    suggestion = get_or_404(session, suggestion_id)
    if suggestion.status != SuggestionStatus.OPEN:
        raise BusinessError(
            PURCHASE_ORDER_STATUS_INVALID,
            f"当前状态 {suggestion.status.value} 不能转采购单",
            http_status=409,
        )

    sku = product_repo.get_sku(session, suggestion.sku_id)
    if sku is None:
        raise BusinessError(REPLENISH_SUGGESTION_NOT_FOUND, "SKU 不存在", http_status=404)

    supplier_id = payload.supplier_id or suggestion.supplier_id or sku.default_supplier_id
    if not supplier_id:
        raise BusinessError(
            REPLENISH_SUGGESTION_NOT_FOUND,
            "该 SKU 没有默认供应商，请先选择供应商或维护 SKU 的默认供应商",
            http_status=400,
        )

    quantity = payload.quantity or suggestion.suggested_qty
    order = purchase_service.create_order(
        session,
        PurchaseOrderCreate(
            supplier_id=supplier_id,
            warehouse_id=payload.warehouse_id or suggestion.warehouse_id,
            remark=payload.remark
            or f"由补货建议 {suggestion.suggestion_no} 生成",
            items=[
                PurchaseOrderItemIn(
                    sku_id=suggestion.sku_id,
                    quantity=quantity,
                    unit_price_cents=payload.unit_price_cents or sku.purchase_price_cents,
                )
            ],
        ),
        buyer_id=operator_id,
    )

    suggestion.status = SuggestionStatus.CONVERTED
    suggestion.purchase_order_id = order.id
    suggestion.converted_at = utcnow()
    # 释放去重键：这条建议已经变成采购单了，下一轮该按新的库存重新评估，
    # 否则 UNIQUE(dedup_key) 会挡住新建议生成。
    suggestion.dedup_key = None
    session.commit()
    return order, suggestion
