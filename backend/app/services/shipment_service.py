"""Warehouse fulfilment: build a pick list, scan it, pack it, ship it.

The pick list is **derived from the inventory ledger**, not from the order lines.
M2 recorded exactly which SKU in which warehouse is being held; those reservation
rows are what a picker actually walks to fetch.  Shipping then converts them into
``order_outbound`` movements, which is the only way stock ever leaves the shelf.

Bundles need no special handling here for the same reason: the reservation rows
are already exploded into component SKUs.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import (
    BARCODE_REQUIRED,
    ORDER_NOT_RESERVED,
    OUTBOUND_STOCK_MISMATCH,
    PICK_INCOMPLETE,
    PICK_QUANTITY_EXCEEDS,
    PICK_WRONG_SKU,
    SHIPMENT_ALREADY_EXISTS,
    SHIPMENT_INVALID_TRANSITION,
    SHIPMENT_NO_ITEMS,
    SHIPMENT_NOT_FOUND,
    SHIPMENT_NOT_PACKED,
    BusinessError,
)
from app.domain import bundle_math
from app.models.base import utcnow
from app.models.order import OrderStatus, SalesOrder
from app.models.product import Sku
from app.models.shipment import (
    PickRecord,
    PickResult,
    Shipment,
    ShipmentItem,
    ShipmentItemStatus,
    ShipmentStatus,
)
from app.models.user import User
from app.repositories import (
    inventory_repo,
    order_repo,
    product_repo,
    shipment_repo,
    user_repo,
    warehouse_repo,
)
from app.schemas.shipment import (
    OutboundLine,
    PickRecordRead,
    ShipmentItemRead,
    ShipmentListRead,
    ShipmentRead,
)
from app.services import combo_service, inventory_service, order_service

#: Ledger rows are always tagged against the *sales order*, never the shipment.
#: The order's outstanding hold is derived by summing its ledger rows, so an
#: outbound tagged with a different ref_type would silently break that chain.
LEDGER_REF = "sales_order"

#: Statuses from which a shipment may still be called off.
CANCELLABLE = {
    ShipmentStatus.PENDING,
    ShipmentStatus.PICKING,
    ShipmentStatus.PICKED,
    ShipmentStatus.PACKED,
}


# ------------------------------------------------------------------- lookups
def get_shipment_or_404(session: Session, shipment_id: int) -> Shipment:
    shipment = shipment_repo.get_shipment(session, shipment_id)
    if shipment is None:
        raise BusinessError(SHIPMENT_NOT_FOUND, http_status=404)
    return shipment


def _resolve_barcode(session: Session, barcode: str) -> Sku | None:
    """Primary barcode first, then the extra barcodes table."""
    sku = product_repo.get_sku_by_barcode(session, barcode)
    if sku is not None:
        return sku
    extra = product_repo.get_barcode(session, barcode)
    if extra is not None:
        return product_repo.get_sku(session, extra.sku_id)
    return None


def _user_name(session: Session, user_id: int | None) -> str:
    if not user_id:
        return ""
    user: User | None = user_repo.get(session, user_id)
    if user is None:
        return ""
    return user.full_name or user.username


def _order_item_sources(session: Session, order: SalesOrder) -> dict[int, tuple[int, bool]]:
    """``component sku_id -> (sales_order_item.id, came_from_a_bundle)``.

    A bundle line fans out into several pick rows, all pointing back at the one
    order line the customer actually bought.
    """
    sources: dict[int, tuple[int, bool]] = {}
    for item in order.items:
        if item.sku is None:
            continue
        pairs = combo_service.component_pairs(session, item.sku_id)
        needed = (
            bundle_math.explode(pairs, item.quantity)
            if pairs
            else [(item.sku_id, item.quantity)]
        )
        for sku_id, _qty in needed:
            sources.setdefault(sku_id, (item.id, bool(pairs)))
    return sources


# ------------------------------------------------------------------- create
def create_shipment(
    session: Session, order: SalesOrder, *, remark: str = "", operator_id: int | None = None
) -> Shipment:
    """Build the pick list for an order that is already holding stock."""
    existing = shipment_repo.get_active_by_order(session, order.id)
    if existing is not None:
        raise BusinessError(
            SHIPMENT_ALREADY_EXISTS,
            f"订单已有进行中的发货单 {existing.shipment_no or existing.id}",
            detail={"shipment_id": existing.id, "shipment_no": existing.shipment_no},
            http_status=409,
        )
    if order.status != OrderStatus.RESERVED:
        raise BusinessError(
            ORDER_NOT_RESERVED,
            f"订单当前状态为 {order.status.value}，只有已占用库存的订单才能生成发货单",
            http_status=409,
        )

    warehouse = order_service.resolve_warehouse(session, order)
    held = order_repo.net_reservations(session, order.id)
    if not held:
        raise BusinessError(SHIPMENT_NO_ITEMS, "订单没有占用任何库存", http_status=400)

    sources = _order_item_sources(session, order)

    # Resolve the standing location of each SKU so the list can be walked in order.
    rows: list[dict] = []
    for sku_id, _warehouse_id, qty in held:
        stock = inventory_repo.get_stock(session, sku_id, warehouse.id)
        location = stock.default_location if stock is not None else None
        sku = product_repo.get_sku(session, sku_id)
        order_item_id, from_bundle = sources.get(sku_id, (None, False))
        rows.append(
            {
                "sku_id": sku_id,
                "quantity": qty,
                "location_id": location.id if location else None,
                "location_code": location.code if location else "",
                "sku_code": sku.sku_code if sku else "",
                "order_item_id": order_item_id,
                "is_bundle_component": from_bundle,
            }
        )

    # 按库位编码排序 = 拣货路线；没有维护库位的排到最后。
    rows.sort(
        key=lambda row: (
            row["location_code"] or settings.PICK_UNASSIGNED_LOCATION_ORDER,
            row["sku_code"],
        )
    )

    shipment: Shipment | None = None
    try:
        # The partial unique index on (order_id) for live shipments is what
        # actually serialises two tablets opening the same pick list.
        with session.begin_nested():
            shipment = shipment_repo.create_shipment(
                session,
                order_id=order.id,
                warehouse_id=warehouse.id,
                status=ShipmentStatus.PENDING,
                remark=remark,
            )
    except IntegrityError:
        session.rollback()
        raise BusinessError(
            SHIPMENT_ALREADY_EXISTS,
            "该订单已有进行中的发货单",
            http_status=409,
        ) from None

    shipment.shipment_no = shipment_repo.next_shipment_no(
        session, settings.SHIPMENT_CODE_PREFIX, shipment.id
    )

    for line_no, row in enumerate(rows, start=1):
        shipment_repo.create_item(
            session,
            shipment_id=shipment.id,
            order_item_id=row["order_item_id"],
            sku_id=row["sku_id"],
            location_id=row["location_id"],
            quantity=row["quantity"],
            picked_qty=0,
            status=ShipmentItemStatus.PENDING,
            line_no=line_no,
        )

    # The order is now in the warehouse's hands, not the operator's.
    order.status = OrderStatus.PICKING
    session.commit()
    session.refresh(shipment)
    return shipment


# ------------------------------------------------------------------ actions
def claim(
    session: Session,
    shipment: Shipment,
    *,
    picker_id: int | None = None,
    operator_id: int | None = None,
) -> Shipment:
    if shipment.status != ShipmentStatus.PENDING:
        raise BusinessError(
            SHIPMENT_INVALID_TRANSITION,
            f"当前状态 {shipment.status.value} 不能领取",
            http_status=409,
        )
    shipment.status = ShipmentStatus.PICKING
    shipment.picker_id = picker_id or operator_id
    session.commit()
    return shipment


def pick(
    session: Session,
    shipment: Shipment,
    *,
    barcode: str,
    quantity: int = 1,
    operator_id: int | None = None,
) -> PickRecord:
    """Validate one scan against the pick list and record the outcome.

    A rejected scan is still written to ``pick_records``: a run of
    ``wrong_sku`` rows is the signal that stock is misplaced on the shelf.
    """
    if shipment.status not in (ShipmentStatus.PENDING, ShipmentStatus.PICKING):
        raise BusinessError(
            SHIPMENT_INVALID_TRANSITION,
            f"当前状态 {shipment.status.value} 不能拣货",
            http_status=409,
        )
    if not barcode or not barcode.strip():
        raise BusinessError(BARCODE_REQUIRED, http_status=400)

    barcode = barcode.strip()
    if shipment.status == ShipmentStatus.PENDING:
        # First scan implicitly claims the job for whoever is holding the scanner.
        shipment.status = ShipmentStatus.PICKING
        shipment.picker_id = shipment.picker_id or operator_id

    sku = _resolve_barcode(session, barcode)
    if sku is None:
        return _reject(
            session,
            shipment,
            barcode=barcode,
            quantity=quantity,
            result=PickResult.BARCODE_NOT_FOUND,
            message=f"条码 {barcode} 不在系统里",
            operator_id=operator_id,
        )

    item = next((row for row in shipment.items if row.sku_id == sku.id), None)
    if item is None:
        return _reject(
            session,
            shipment,
            barcode=barcode,
            quantity=quantity,
            result=PickResult.WRONG_SKU,
            message=f"{sku.sku_code} 不在本单拣货清单里，已拦截",
            sku_id=sku.id,
            operator_id=operator_id,
        )

    remaining = item.quantity - item.picked_qty
    if remaining <= 0:
        return _reject(
            session,
            shipment,
            barcode=barcode,
            quantity=quantity,
            result=PickResult.OVER_QUANTITY,
            message=f"{sku.sku_code} 已经拣够了",
            sku_id=sku.id,
            shipment_item_id=item.id,
            operator_id=operator_id,
        )

    # Atomic: a second scanner cannot push the line past its quantity.
    if not shipment_repo.try_pick_atomic(session, item.id, quantity):
        session.refresh(item)
        left = max(0, item.quantity - item.picked_qty)
        return _reject(
            session,
            shipment,
            barcode=barcode,
            quantity=quantity,
            result=PickResult.OVER_QUANTITY,
            message=f"本次扫 {quantity} 件，但 {sku.sku_code} 只剩 {left} 件未拣",
            sku_id=sku.id,
            shipment_item_id=item.id,
            operator_id=operator_id,
        )

    session.refresh(item)
    item.picked_by = operator_id
    if item.is_done:
        item.status = ShipmentItemStatus.PICKED
        item.picked_at = utcnow()
    _mark_picked_if_complete(session, shipment)

    record = shipment_repo.create_pick_record(
        session,
        shipment_id=shipment.id,
        shipment_item_id=item.id,
        sku_id=sku.id,
        barcode=barcode,
        quantity=quantity,
        result=PickResult.OK,
        accepted=True,
        message=f"已拣 {sku.sku_code} × {quantity}",
        operator_id=operator_id,
    )
    session.commit()
    return record


def _mark_picked_if_complete(session: Session, shipment: Shipment) -> None:
    """Flip the shipment to ``picked`` once nothing is left outstanding.

    Counted with a query rather than from the in-memory items, because the scan
    itself was applied by a bulk UPDATE.
    """
    if shipment_repo.count_pending_items(session, shipment.id) == 0:
        shipment.status = ShipmentStatus.PICKED
        shipment.picked_at = utcnow()


def pick_manual(
    session: Session,
    shipment: Shipment,
    *,
    shipment_item_id: int,
    quantity: int,
    operator_id: int | None = None,
) -> PickRecord:
    """Confirm a line without a barcode (paper-pick warehouses)."""
    if shipment.status not in (ShipmentStatus.PENDING, ShipmentStatus.PICKING):
        raise BusinessError(
            SHIPMENT_INVALID_TRANSITION,
            f"当前状态 {shipment.status.value} 不能拣货",
            http_status=409,
        )

    item = next((row for row in shipment.items if row.id == shipment_item_id), None)
    if item is None:
        raise BusinessError(
            SHIPMENT_NOT_FOUND, detail={"shipment_item_id": shipment_item_id}, http_status=404
        )

    remaining = item.quantity - item.picked_qty
    if quantity > remaining:
        raise BusinessError(
            PICK_QUANTITY_EXCEEDS,
            f"只剩 {remaining} 件未拣",
            detail={"remaining": remaining, "requested": quantity},
            http_status=409,
        )

    if shipment.status == ShipmentStatus.PENDING:
        shipment.status = ShipmentStatus.PICKING
        shipment.picker_id = shipment.picker_id or operator_id

    if not shipment_repo.try_pick_atomic(session, item.id, quantity):
        session.refresh(item)
        left = max(0, item.quantity - item.picked_qty)
        raise BusinessError(
            PICK_QUANTITY_EXCEEDS,
            f"只剩 {left} 件未拣",
            detail={"remaining": left, "requested": quantity},
            http_status=409,
        )

    session.refresh(item)
    item.picked_by = operator_id
    if item.is_done:
        item.status = ShipmentItemStatus.PICKED
        item.picked_at = utcnow()
    _mark_picked_if_complete(session, shipment)

    record = shipment_repo.create_pick_record(
        session,
        shipment_id=shipment.id,
        shipment_item_id=item.id,
        sku_id=item.sku_id,
        barcode="",
        quantity=quantity,
        result=PickResult.OK,
        accepted=True,
        message=f"手工确认 {item.sku.sku_code if item.sku else item.sku_id} × {quantity}",
        operator_id=operator_id,
    )
    session.commit()
    return record


def _reject(
    session: Session,
    shipment: Shipment,
    *,
    barcode: str,
    quantity: int,
    result: PickResult,
    message: str,
    sku_id: int | None = None,
    shipment_item_id: int | None = None,
    operator_id: int | None = None,
) -> PickRecord:
    record = shipment_repo.create_pick_record(
        session,
        shipment_id=shipment.id,
        shipment_item_id=shipment_item_id,
        sku_id=sku_id,
        barcode=barcode,
        quantity=quantity,
        result=result,
        accepted=False,
        message=message,
        operator_id=operator_id,
    )
    session.commit()
    return record


def pack(
    session: Session,
    shipment: Shipment,
    *,
    package_count: int = 1,
    weight_g: int = 0,
    remark: str = "",
    operator_id: int | None = None,
) -> Shipment:
    """复核打包.  Gate: nothing leaves unless every line was picked."""
    if shipment.status not in (
        ShipmentStatus.PENDING,
        ShipmentStatus.PICKING,
        ShipmentStatus.PICKED,
    ):
        raise BusinessError(
            SHIPMENT_INVALID_TRANSITION,
            f"当前状态 {shipment.status.value} 不能复核打包",
            http_status=409,
        )

    pending = shipment_repo.count_pending_items(session, shipment.id)
    if pending:
        # Report the shortfall precisely — "还有几件没拣" beats "状态不对".
        if not settings.SHIPMENT_ALLOW_PARTIAL_PICK:
            raise BusinessError(
                PICK_INCOMPLETE,
                detail={
                    "picked": shipment.picked_quantity,
                    "required": shipment.total_quantity,
                },
                http_status=409,
            )
        if shipment.picked_quantity <= 0:
            raise BusinessError(
                PICK_INCOMPLETE, "一件都没有拣，不能复核打包", http_status=409
            )
        # 短拣放行：按实际拣到的数量继续。
        shipment.status = ShipmentStatus.PICKED
        shipment.picked_at = shipment.picked_at or utcnow()

    shipment.status = ShipmentStatus.PACKED
    shipment.packed_by = operator_id
    shipment.packed_at = utcnow()
    shipment.package_count = package_count
    shipment.weight_g = weight_g
    if remark:
        shipment.remark = f"{shipment.remark} | {remark}"[:255]
    session.commit()
    return shipment


def ship(
    session: Session,
    shipment: Shipment,
    *,
    carrier: str = "",
    tracking_no: str = "",
    remark: str = "",
    operator_id: int | None = None,
) -> list[tuple[int, int, int]]:
    """出库发货：把占用转成真正的出库流水，实际库存与占用一起减少。

    Returns ``[(sku_id, warehouse_id, quantity), ...]`` that left the shelf.
    """
    if shipment.status == ShipmentStatus.SHIPPED:
        raise BusinessError(
            SHIPMENT_INVALID_TRANSITION, "该发货单已经出库，不能重复发货", http_status=409
        )
    if shipment.status == ShipmentStatus.CANCELLED:
        raise BusinessError(
            SHIPMENT_INVALID_TRANSITION, "该发货单已取消，不能发货", http_status=409
        )
    if shipment.status != ShipmentStatus.PACKED:
        raise BusinessError(
            SHIPMENT_NOT_PACKED,
            f"当前状态 {shipment.status.value}，必须先复核打包才能出库",
            http_status=409,
        )

    outbound: list[tuple[int, int, int]] = []
    for item in shipment.items:
        if item.picked_qty <= 0:
            continue
        # Idempotency key makes a retried request a no-op instead of a double ship.
        inventory_service.outbound(
            session,
            sku_id=item.sku_id,
            warehouse_id=shipment.warehouse_id,
            quantity=item.picked_qty,
            location_id=item.location_id,
            ref_type=LEDGER_REF,
            ref_id=shipment.order_id,
            operator_id=operator_id,
            remark=f"订单出库 {shipment.shipment_no}",
            idempotency_key=f"ship:{shipment.id}:{item.sku_id}:{shipment.warehouse_id}",
        )
        outbound.append((item.sku_id, shipment.warehouse_id, item.picked_qty))

    remaining = order_repo.net_reservations(session, shipment.order_id)
    if remaining:
        if not settings.SHIPMENT_ALLOW_PARTIAL_PICK:
            # The order still holds stock that was not shipped — refuse rather
            # than silently leave a stuck reservation behind.
            session.rollback()
            raise BusinessError(
                OUTBOUND_STOCK_MISMATCH,
                "出库后订单仍有未释放的占用，请检查拣货数量与库存流水",
                detail={"remaining": [{"sku_id": s, "qty": q} for s, _w, q in remaining]},
                http_status=409,
            )
        # 短拣发货：把没发出去的那部分占用放掉，否则订单会一直挂着幽灵占用。
        for sku_id, warehouse_id, qty in remaining:
            inventory_service.release(
                session,
                sku_id=sku_id,
                warehouse_id=warehouse_id,
                quantity=qty,
                ref_type=LEDGER_REF,
                ref_id=shipment.order_id,
                operator_id=operator_id,
                remark=f"短拣释放 {shipment.shipment_no}",
            )

    shipment.status = ShipmentStatus.SHIPPED
    shipment.carrier = carrier
    shipment.tracking_no = tracking_no
    shipment.shipped_by = operator_id
    shipment.shipped_at = utcnow()
    if remark:
        shipment.remark = f"{shipment.remark} | {remark}"[:255]

    order = order_service.get_order_or_404(session, shipment.order_id)
    order.status = OrderStatus.SHIPPED

    session.commit()
    return outbound


def cancel(
    session: Session,
    shipment: Shipment,
    *,
    reason: str = "",
    operator_id: int | None = None,
) -> Shipment:
    """Call off the pick job.  Stock stays reserved for the order."""
    if shipment.status not in CANCELLABLE:
        raise BusinessError(
            SHIPMENT_INVALID_TRANSITION,
            f"当前状态 {shipment.status.value} 不能取消",
            http_status=409,
        )

    shipment.status = ShipmentStatus.CANCELLED
    shipment.cancelled_at = utcnow()
    if reason:
        shipment.remark = f"{shipment.remark} | 取消：{reason}"[:255]

    # Hand the order back so it can be re-picked or cancelled as a whole.
    order = order_service.get_order_or_404(session, shipment.order_id)
    if order.status == OrderStatus.PICKING:
        order.status = OrderStatus.RESERVED

    session.commit()
    return shipment


# ------------------------------------------------------------------ read views
def to_item_read(item: ShipmentItem) -> ShipmentItemRead:
    sku = item.sku
    return ShipmentItemRead(
        id=item.id,
        line_no=item.line_no,
        sku_id=item.sku_id,
        sku_code=sku.sku_code if sku else "",
        sku_name=sku.display_name if sku else "",
        barcode=(sku.barcode or "") if sku else "",
        location_id=item.location_id,
        location_code=item.location.code if item.location else "",
        location_name=item.location.name if item.location else "",
        quantity=item.quantity,
        picked_qty=item.picked_qty,
        status=item.status,
        is_bundle_component=bool(item.order_item and item.order_item.is_bundle),
        remark=item.remark,
    )


def to_shipment_read(session: Session, shipment: Shipment) -> ShipmentRead:
    order = shipment.order
    warehouse = shipment.warehouse
    items = sorted(shipment.items, key=lambda row: row.line_no)
    return ShipmentRead(
        id=shipment.id,
        shipment_no=shipment.shipment_no,
        order_id=shipment.order_id,
        order_no=order.order_no if order else "",
        channel_code=order.channel.code if order and order.channel else "",
        channel_order_no=order.channel_order_no if order else "",
        buyer_nick=order.buyer_nick if order else "",
        warehouse_id=shipment.warehouse_id,
        warehouse_code=warehouse.code if warehouse else "",
        warehouse_name=warehouse.name if warehouse else "",
        status=shipment.status,
        picker_id=shipment.picker_id,
        picker_name=_user_name(session, shipment.picker_id),
        picked_at=shipment.picked_at,
        packed_by=shipment.packed_by,
        packed_by_name=_user_name(session, shipment.packed_by),
        packed_at=shipment.packed_at,
        package_count=shipment.package_count,
        weight_g=shipment.weight_g,
        carrier=shipment.carrier,
        tracking_no=shipment.tracking_no,
        shipped_at=shipment.shipped_at,
        remark=shipment.remark,
        total_quantity=shipment.total_quantity,
        picked_quantity=shipment.picked_quantity,
        is_fully_picked=shipment.is_fully_picked,
        items=[to_item_read(item) for item in items],
        created_at=shipment.created_at,
    )


def to_list_read(session: Session, shipment: Shipment) -> ShipmentListRead:
    order = shipment.order
    warehouse = shipment.warehouse
    return ShipmentListRead(
        id=shipment.id,
        shipment_no=shipment.shipment_no,
        order_no=order.order_no if order else "",
        channel_code=order.channel.code if order and order.channel else "",
        channel_order_no=order.channel_order_no if order else "",
        buyer_nick=order.buyer_nick if order else "",
        warehouse_code=warehouse.code if warehouse else "",
        status=shipment.status,
        picker_name=_user_name(session, shipment.picker_id),
        total_quantity=shipment.total_quantity,
        picked_quantity=shipment.picked_quantity,
        carrier=shipment.carrier,
        tracking_no=shipment.tracking_no,
        created_at=shipment.created_at,
    )


def to_outbound_lines(session: Session, rows: list[tuple[int, int, int]]) -> list[OutboundLine]:
    lines: list[OutboundLine] = []
    for sku_id, warehouse_id, qty in rows:
        sku = product_repo.get_sku(session, sku_id)
        warehouse = warehouse_repo.get(session, warehouse_id)
        lines.append(
            OutboundLine(
                sku_id=sku_id,
                sku_code=sku.sku_code if sku else "",
                warehouse_code=warehouse.code if warehouse else "",
                quantity=qty,
            )
        )
    return lines


def to_pick_record_read(record: PickRecord) -> PickRecordRead:
    return PickRecordRead(
        id=record.id,
        shipment_id=record.shipment_id,
        shipment_item_id=record.shipment_item_id,
        barcode=record.barcode,
        quantity=record.quantity,
        result=record.result,
        accepted=record.accepted,
        message=record.message,
        sku_id=record.sku_id,
        sku_code=record.sku.sku_code if record.sku else "",
        operator_id=record.operator_id,
        operator_name=record.operator.full_name if record.operator else "",
        created_at=record.created_at,
    )
