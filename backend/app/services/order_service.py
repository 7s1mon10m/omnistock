"""Order lifecycle: reservation, release, cancellation and retry.

Two design decisions worth calling out:

* **Reservations are recorded in the ledger, not in a separate table.** What an
  order currently holds is ``sum(qty_delta)`` over its ``order_reserve`` and
  ``order_release`` rows.  Cancelling therefore releases exactly what was
  reserved, even if the bundle definition changed in between.
* **A shortage never leaves a half-reserved order in the default strategy.**
  ``exception`` mode refuses the whole order; ``partial`` mode reserves what it
  can and books the remainder as an exception for a later retry.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import (
    ORDER_NO_ITEMS,
    ORDER_NOT_FOUND,
    ORDER_STATUS_INVALID_TRANSITION,
    WAREHOUSE_NOT_FOUND,
    BusinessError,
)
from app.domain import bundle_math
from app.models.base import utcnow
from app.models.channel import ChannelShop
from app.models.order import (
    ExceptionStatus,
    ExceptionType,
    OrderException,
    OrderStatus,
    OrderSyncLog,
    SalesOrder,
)
from app.models.warehouse import Warehouse
from app.repositories import order_repo, product_repo, warehouse_repo
from app.schemas.order import (
    OrderExceptionRead,
    OrderItemRead,
    OrderListRead,
    OrderRead,
    ReservationLine,
    SyncLogRead,
)
from app.services import combo_service, inventory_service as inventory_svc

#: Statuses from which an order may still be cancelled.
CANCELLABLE = {
    OrderStatus.PENDING_PAYMENT,
    OrderStatus.PENDING_FULFILLMENT,
    OrderStatus.RESERVED,
    OrderStatus.EXCEPTION,
}

LEDGER_REF = "sales_order"


@dataclass
class ReservationResult:
    """Outcome of one reservation attempt."""

    #: ``(sku_id, warehouse_id, qty)`` actually reserved during this attempt.
    lines: list[tuple[int, int, int]] = field(default_factory=list)
    exceptions: list[OrderException] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.exceptions


# ------------------------------------------------------------------- lookups
def get_order_or_404(session: Session, order_id: int) -> SalesOrder:
    order = order_repo.get_order(session, order_id)
    if order is None:
        raise BusinessError(ORDER_NOT_FOUND, http_status=404)
    return order


def resolve_warehouse(session: Session, order: SalesOrder) -> Warehouse:
    """The warehouse this order ships from; defaults to the main one."""
    warehouse: Warehouse | None = None
    if order.warehouse_id:
        warehouse = warehouse_repo.get(session, order.warehouse_id)
    if warehouse is None:
        warehouse = warehouse_repo.get_by_code(session, settings.DEFAULT_WAREHOUSE_CODE)
    if warehouse is None:
        actives = warehouse_repo.list_all(session, active_only=True)
        warehouse = actives[0] if actives else None
    if warehouse is None:
        raise BusinessError(WAREHOUSE_NOT_FOUND, "系统里还没有可用仓库", http_status=404)
    order.warehouse_id = warehouse.id
    return warehouse


def requirements(session: Session, order: SalesOrder, warehouse_id: int) -> list[tuple[int, int]]:
    """``[(component_sku_id, total_qty), ...]`` needed to fulfil this order.

    Bundle lines are exploded into their components and merged, so an order with
    two bundles sharing a component reserves it only once, with the summed qty.
    """
    merged: dict[int, int] = {}
    for item in order.items:
        sku = item.sku
        if sku is None:
            continue
        pairs = combo_service.component_pairs(session, sku.id)
        needed = (
            bundle_math.explode(pairs, item.quantity)
            if pairs
            else [(sku.id, item.quantity)]
        )
        for sku_id, qty in needed:
            merged[sku_id] = merged.get(sku_id, 0) + qty
    return sorted(merged.items())


def held_now(session: Session, order: SalesOrder) -> dict[tuple[int, int], int]:
    return {(sku_id, wh): qty for sku_id, wh, qty in order_repo.net_reservations(session, order.id)}


# --------------------------------------------------------------- reservation
def _reserve_up_to(
    session: Session,
    *,
    sku_id: int,
    warehouse_id: int,
    quantity: int,
    order_id: int,
    operator_id: int | None,
) -> int:
    """Reserve as much as availability allows right now; returns the amount taken.

    Availability is re-read on every attempt because a concurrent order may take
    stock between the pre-check and the write.
    """
    remaining = quantity
    for _ in range(4):
        if remaining <= 0:
            break
        available = inventory_svc.available_for(session, sku_id, warehouse_id)
        take = min(remaining, available)
        if take <= 0:
            break
        try:
            inventory_svc.reserve(
                session,
                sku_id=sku_id,
                warehouse_id=warehouse_id,
                quantity=take,
                ref_type=LEDGER_REF,
                ref_id=order_id,
                operator_id=operator_id,
                remark="电商订单占用",
            )
        except BusinessError:
            # Lost the race; loop and re-read availability.
            continue
        remaining -= take
    return quantity - remaining


def reserve_order(
    session: Session,
    order: SalesOrder,
    *,
    operator_id: int | None = None,
    strategy: str | None = None,
    commit: bool = True,
) -> ReservationResult:
    """Try to hold stock for the whole order.

    Existing open exceptions are closed first so the exception list always
    reflects the *current* attempt rather than accumulating history.
    """
    strategy = strategy or settings.ORDER_SHORTAGE_STRATEGY
    warehouse = resolve_warehouse(session, order)
    needs = requirements(session, order, warehouse.id)
    if not needs:
        raise BusinessError(ORDER_NO_ITEMS, "订单没有可占用的商品行", http_status=400)

    held = held_now(session, order)
    order_repo.resolve_open_exceptions(session, order.id, status=ExceptionStatus.RESOLVED)

    # What is still missing after whatever is already held.
    pending: list[tuple[int, int, int]] = []  # sku_id, needed_more, available
    for sku_id, need in needs:
        remaining = need - held.get((sku_id, warehouse.id), 0)
        if remaining <= 0:
            continue
        pending.append(
            (sku_id, remaining, inventory_svc.available_for(session, sku_id, warehouse.id))
        )

    result = ReservationResult()

    if not pending:
        order.status = OrderStatus.RESERVED
        if commit:
            session.commit()
        return result

    if strategy == "exception":
        shortages = [(sku, need, avail) for sku, need, avail in pending if avail < need]
        if shortages:
            for sku_id, need, avail in shortages:
                result.exceptions.append(
                    _record_shortage(session, order, sku_id, need, avail, warehouse.id)
                )
            order.status = OrderStatus.EXCEPTION
            if commit:
                session.commit()
            return result

    # Either nothing is short, or the caller asked for partial fulfilment.
    for sku_id, need, _available in pending:
        got = _reserve_up_to(
            session,
            sku_id=sku_id,
            warehouse_id=warehouse.id,
            quantity=need,
            order_id=order.id,
            operator_id=operator_id,
        )
        if got:
            result.lines.append((sku_id, warehouse.id, got))
        if got < need:
            result.exceptions.append(
                _record_shortage(
                    session,
                    order,
                    sku_id,
                    need,
                    got,
                    warehouse.id,
                    message_suffix="（部分占用）" if got else "",
                )
            )

    order.status = OrderStatus.EXCEPTION if result.exceptions else OrderStatus.RESERVED
    if commit:
        session.commit()
    return result


def _record_shortage(
    session: Session,
    order: SalesOrder,
    sku_id: int,
    required: int,
    available: int,
    warehouse_id: int,
    message_suffix: str = "",
) -> OrderException:
    sku = product_repo.get_sku(session, sku_id)
    label = sku.sku_code if sku else f"#{sku_id}"
    return order_repo.create_exception(
        session,
        order_id=order.id,
        sku_id=sku_id,
        type=ExceptionType.STOCK_SHORTAGE,
        required_qty=required,
        available_qty=available,
        message=f"{label} 可售 {available}，需要 {required}{message_suffix}",
    )


# ------------------------------------------------------------------- actions
def mark_paid(
    session: Session,
    order: SalesOrder,
    *,
    paid_at: dt.datetime | None = None,
    operator_id: int | None = None,
) -> ReservationResult:
    if order.status != OrderStatus.PENDING_PAYMENT:
        raise BusinessError(
            ORDER_STATUS_INVALID_TRANSITION,
            f"只有待支付的订单可以标记付款，当前为 {order.status.value}",
            http_status=409,
        )
    order.paid_at = paid_at or utcnow()
    order.status = OrderStatus.PENDING_FULFILLMENT
    session.flush()
    result = reserve_order(session, order, operator_id=operator_id, commit=False)
    session.commit()
    return result


def retry_reserve(
    session: Session, order: SalesOrder, *, operator_id: int | None = None
) -> ReservationResult:
    """Re-attempt the still-missing part of an exception order."""
    if order.status not in (OrderStatus.EXCEPTION, OrderStatus.PENDING_FULFILLMENT):
        raise BusinessError(
            ORDER_STATUS_INVALID_TRANSITION,
            f"当前状态 {order.status.value} 不需要重新占用",
            http_status=409,
        )
    if order.paid_at is None:
        raise BusinessError(
            ORDER_STATUS_INVALID_TRANSITION, "订单尚未支付，不能占用库存", http_status=409
        )
    return reserve_order(session, order, operator_id=operator_id)


def cancel_order(
    session: Session,
    order: SalesOrder,
    *,
    reason: str = "",
    operator_id: int | None = None,
) -> list[tuple[int, int, int]]:
    """Release everything the order holds and mark it cancelled."""
    if order.status not in CANCELLABLE:
        raise BusinessError(
            ORDER_STATUS_INVALID_TRANSITION,
            f"当前状态 {order.status.value} 的订单不能取消",
            http_status=409,
        )

    released: list[tuple[int, int, int]] = []
    for sku_id, warehouse_id, qty in order_repo.net_reservations(session, order.id):
        inventory_svc.release(
            session,
            sku_id=sku_id,
            warehouse_id=warehouse_id,
            quantity=qty,
            ref_type=LEDGER_REF,
            ref_id=order.id,
            operator_id=operator_id,
            remark=f"订单取消释放：{reason}"[:255] if reason else "订单取消释放",
        )
        released.append((sku_id, warehouse_id, qty))

    order_repo.resolve_open_exceptions(
        session, order.id, status=ExceptionStatus.IGNORED, resolved_by=operator_id
    )
    order.status = OrderStatus.CANCELLED
    if reason:
        order.remark = f"{order.remark} | 取消原因：{reason}"[:255]
    session.commit()
    return released


# ------------------------------------------------------------------ read views
def reservation_lines(session: Session, order: SalesOrder) -> list[ReservationLine]:
    lines: list[ReservationLine] = []
    for sku_id, warehouse_id, qty in order_repo.net_reservations(session, order.id):
        sku = product_repo.get_sku(session, sku_id)
        warehouse = warehouse_repo.get(session, warehouse_id)
        lines.append(
            ReservationLine(
                sku_id=sku_id,
                sku_code=sku.sku_code if sku else "",
                warehouse_id=warehouse_id,
                warehouse_code=warehouse.code if warehouse else "",
                quantity=qty,
            )
        )
    return lines


def to_lines(session: Session, raw: list[tuple[int, int, int]]) -> list[ReservationLine]:
    lines: list[ReservationLine] = []
    for sku_id, warehouse_id, qty in raw:
        sku = product_repo.get_sku(session, sku_id)
        warehouse = warehouse_repo.get(session, warehouse_id)
        lines.append(
            ReservationLine(
                sku_id=sku_id,
                sku_code=sku.sku_code if sku else "",
                warehouse_id=warehouse_id,
                warehouse_code=warehouse.code if warehouse else "",
                quantity=qty,
            )
        )
    return lines


def to_order_read(session: Session, order: SalesOrder) -> OrderRead:
    return OrderRead(
        id=order.id,
        order_no=order.order_no,
        channel_id=order.channel_id,
        channel_code=order.channel.code if order.channel else "",
        channel_name=order.channel.name if order.channel else "",
        shop_id=order.shop_id,
        shop_code=order.shop.code if order.shop else "",
        channel_order_no=order.channel_order_no,
        status=order.status,
        warehouse_id=order.warehouse_id,
        warehouse_code=order.warehouse.code if order.warehouse else "",
        buyer_nick=order.buyer_nick,
        total_amount_cents=order.total_amount_cents,
        total_quantity=order.total_quantity,
        is_bundle=order.is_bundle,
        paid_at=order.paid_at,
        source=order.source,
        remark=order.remark,
        items=[_to_item_read(item) for item in order.items],
        reservations=reservation_lines(session, order),
        open_exceptions=order_repo.count_open_exceptions(session, order.id),
        created_at=order.created_at,
    )


def _to_item_read(item) -> OrderItemRead:
    return OrderItemRead(
        id=item.id,
        line_no=item.line_no,
        channel_product_code=item.channel_product_code,
        sku_id=item.sku_id,
        sku_code=item.sku.sku_code if item.sku else "",
        sku_name=item.sku.display_name if item.sku else "",
        quantity=item.quantity,
        unit_price_cents=item.unit_price_cents,
        is_bundle=item.is_bundle,
    )


def to_list_read(order: SalesOrder) -> OrderListRead:
    return OrderListRead(
        id=order.id,
        order_no=order.order_no,
        channel_code=order.channel.code if order.channel else "",
        shop_code=order.shop.code if order.shop else "",
        channel_order_no=order.channel_order_no,
        status=order.status,
        buyer_nick=order.buyer_nick,
        total_amount_cents=order.total_amount_cents,
        total_quantity=order.total_quantity,
        item_count=len(order.items),
        is_bundle=order.is_bundle,
        source=order.source,
        created_at=order.created_at,
    )


def to_exception_read(exc: OrderException) -> OrderExceptionRead:
    return OrderExceptionRead(
        id=exc.id,
        order_id=exc.order_id,
        order_no=exc.order.order_no if exc.order else "",
        channel_order_no=exc.order.channel_order_no if exc.order else "",
        sku_id=exc.sku_id,
        sku_code=exc.sku.sku_code if exc.sku else "",
        sku_name=exc.sku.display_name if exc.sku else "",
        warehouse_code=exc.order.warehouse.code
        if exc.order and exc.order.warehouse
        else "",
        type=exc.type,
        status=exc.status,
        required_qty=exc.required_qty,
        available_qty=exc.available_qty,
        shortage_qty=exc.shortage_qty,
        message=exc.message,
        created_at=exc.created_at,
    )


def to_sync_log_read(log: OrderSyncLog) -> SyncLogRead:
    return SyncLogRead(
        id=log.id,
        channel_id=log.channel_id,
        channel_code=log.channel.code if log.channel else "",
        shop_id=log.shop_id,
        channel_order_no=log.channel_order_no,
        order_id=log.order_id,
        batch_id=log.batch_id,
        result=log.result,
        message=log.message,
        created_at=log.created_at,
    )


def shop_belongs_to_channel(shop: ChannelShop, channel_id: int) -> bool:
    return shop.channel_id == channel_id
