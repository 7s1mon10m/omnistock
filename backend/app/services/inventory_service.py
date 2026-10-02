"""Inventory movements.

Every stock change in OmniStock funnels through :func:`_apply`, which

1. takes a row lock on ``inventory_stocks`` (先到先得),
2. applies the signed deltas,
3. writes an immutable ``inventory_transactions`` row carrying the before/after
   snapshot.

Nothing else is allowed to touch a stock number.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import (
    ADJUST_REASON_REQUIRED,
    BusinessError,
    INSUFFICIENT_STOCK,
    INVENTORY_ADJUST_ZERO_DELTA,
    INVENTORY_CONCURRENT_CONFLICT,
    LOCATION_NOT_FOUND,
    OUTBOUND_STOCK_MISMATCH,
    RECEIPT_QUANTITY_INVALID,
    SKU_NOT_FOUND,
    TRANSFER_QUANTITY_INVALID,
    WAREHOUSE_NOT_FOUND,
)
from app.domain import stock_formula
from app.models.inventory import InventoryStock, InventoryTransaction, InventoryTransactionType
from app.repositories import inventory_repo, product_repo, warehouse_repo
from app.schemas.inventory import (
    InventoryAdjustRequest,
    InventoryStockRead,
    InventoryTransactionRead,
)
from app.utils.pagination import PageResult


# ------------------------------------------------------------------ stock rows
def _lock_or_create(
    session: Session, sku_id: int, warehouse_id: int, safety_qty: int = 0
) -> InventoryStock:
    """Lock the stock row, creating it first when the SKU is new to a warehouse."""
    stock = inventory_repo.lock_stock(session, sku_id, warehouse_id)
    if stock is not None:
        return stock

    try:
        # A savepoint keeps a concurrent insert from poisoning our transaction.
        with session.begin_nested():
            stock = inventory_repo.create_stock(
                session, sku_id=sku_id, warehouse_id=warehouse_id, safety_qty=safety_qty
            )
    except IntegrityError:
        stock = inventory_repo.lock_stock(session, sku_id, warehouse_id)

    if stock is None:
        raise BusinessError(INVENTORY_CONCURRENT_CONFLICT, http_status=409)
    return stock


def ensure_stock_for_sku(session: Session, sku, warehouse_ids: list[int] | None = None) -> int:
    """Create a zero-stock row for every active warehouse; returns how many."""
    if warehouse_ids is None:
        warehouse_ids = [w.id for w in warehouse_repo.list_all(session, active_only=True)]
    created = 0
    for warehouse_id in warehouse_ids:
        if inventory_repo.get_stock(session, sku.id, warehouse_id) is None:
            inventory_repo.create_stock(
                session,
                sku_id=sku.id,
                warehouse_id=warehouse_id,
                safety_qty=sku.safety_qty,
            )
            created += 1
    return created


def get_stock_or_zero(session: Session, sku_id: int, warehouse_id: int) -> InventoryStock | None:
    return inventory_repo.get_stock(session, sku_id, warehouse_id)


def available_for(session: Session, sku_id: int, warehouse_id: int) -> int:
    stock = inventory_repo.get_stock(session, sku_id, warehouse_id)
    if stock is None:
        return 0
    return stock.available_qty


# --------------------------------------------------------------------- ledger
def _apply(
    session: Session,
    *,
    sku_id: int,
    warehouse_id: int,
    type_: InventoryTransactionType,
    qty_delta: int = 0,
    reserved_delta: int = 0,
    in_transit_delta: int = 0,
    defective_delta: int = 0,
    repair_delta: int = 0,
    location_id: int | None = None,
    ref_type: str = "",
    ref_id: int | None = None,
    operator_id: int | None = None,
    remark: str = "",
    idempotency_key: str | None = None,
    safety_qty: int = 0,
    allow_negative: bool | None = None,
) -> InventoryTransaction:
    """Apply one movement and append its ledger row.  Caller commits."""
    if idempotency_key:
        existing = inventory_repo.get_transaction_by_idempotency(session, idempotency_key)
        if existing is not None:
            # A replayed message must not move stock twice.
            return existing

    allow_negative = (
        settings.INVENTORY_ALLOW_NEGATIVE if allow_negative is None else allow_negative
    )

    stock = _lock_or_create(session, sku_id, warehouse_id, safety_qty=safety_qty)

    on_hand_before = stock.on_hand_qty
    reserved_before = stock.reserved_qty
    in_transit_before = stock.in_transit_qty
    defective_before = stock.defective_qty

    new_on_hand = on_hand_before + qty_delta
    new_reserved = reserved_before + reserved_delta
    new_in_transit = in_transit_before + in_transit_delta
    new_defective = defective_before + defective_delta
    new_repair = stock.repair_qty + repair_delta

    if not allow_negative and (
        new_on_hand < 0 or new_reserved < 0 or new_in_transit < 0 or new_defective < 0 or new_repair < 0
    ):
        raise BusinessError(
            INSUFFICIENT_STOCK,
            detail={
                "sku_id": sku_id,
                "warehouse_id": warehouse_id,
                "on_hand": on_hand_before,
                "reserved": reserved_before,
                "in_transit": in_transit_before,
                "requested": qty_delta if qty_delta else reserved_delta,
            },
            http_status=409,
        )

    stock.on_hand_qty = new_on_hand
    stock.reserved_qty = new_reserved
    stock.in_transit_qty = new_in_transit
    stock.defective_qty = new_defective
    stock.repair_qty = new_repair
    # Bump the optimistic-lock version on every movement.
    stock.version += 1

    return inventory_repo.append_transaction(
        session,
        sku_id=sku_id,
        warehouse_id=warehouse_id,
        location_id=location_id,
        type=type_,
        qty_delta=qty_delta if qty_delta else reserved_delta,
        on_hand_before=on_hand_before,
        on_hand_after=stock.on_hand_qty,
        reserved_before=reserved_before,
        reserved_after=stock.reserved_qty,
        in_transit_before=in_transit_before,
        in_transit_after=stock.in_transit_qty,
        defective_before=defective_before,
        defective_after=stock.defective_qty,
        ref_type=ref_type,
        ref_id=ref_id,
        operator_id=operator_id,
        idempotency_key=idempotency_key,
        remark=remark,
    )


# ---------------------------------------------------------------- public API
def adjust(
    session: Session, payload: InventoryAdjustRequest, operator_id: int | None = None
) -> InventoryTransaction:
    """Manual stock correction.  A reason is mandatory and lands in the ledger."""
    if not payload.reason or not payload.reason.strip():
        raise BusinessError(ADJUST_REASON_REQUIRED, http_status=409)
    if payload.qty_delta == 0 and settings.INVENTORY_REJECT_ZERO_DELTA:
        raise BusinessError(INVENTORY_ADJUST_ZERO_DELTA, http_status=400)

    sku = product_repo.get_sku(session, payload.sku_id)
    if sku is None:
        raise BusinessError(SKU_NOT_FOUND, http_status=404)
    warehouse = warehouse_repo.get(session, payload.warehouse_id)
    if warehouse is None:
        raise BusinessError(WAREHOUSE_NOT_FOUND, http_status=404)

    tx = _apply(
        session,
        sku_id=payload.sku_id,
        warehouse_id=payload.warehouse_id,
        type_=InventoryTransactionType.MANUAL_ADJUST,
        qty_delta=payload.qty_delta,
        location_id=payload.location_id,
        ref_type="manual",
        operator_id=operator_id,
        remark=payload.reason.strip(),
        idempotency_key=payload.idempotency_key,
        safety_qty=sku.safety_qty,
    )
    session.commit()
    return tx


def reserve(
    session: Session,
    *,
    sku_id: int,
    warehouse_id: int,
    quantity: int,
    ref_type: str = "",
    ref_id: int | None = None,
    operator_id: int | None = None,
    idempotency_key: str | None = None,
    remark: str = "",
) -> InventoryTransaction:
    """Occupy stock for an order line.  Raises when sellable stock is short.

    The availability test and the write happen in one conditional ``UPDATE``
    (see :func:`app.repositories.inventory_repo.try_reserve_atomic`), which is
    what makes "先到先得" hold under concurrency on any database.

    M2 drives this from the order sync flow; M1 exposes it directly so the rule
    can be demonstrated and tested.
    """
    if quantity <= 0:
        raise BusinessError(INVENTORY_ADJUST_ZERO_DELTA, "占用数量必须大于 0", http_status=400)

    if idempotency_key:
        existing = inventory_repo.get_transaction_by_idempotency(session, idempotency_key)
        if existing is not None:
            return existing

    stock = _lock_or_create(session, sku_id, warehouse_id)

    if not inventory_repo.try_reserve_atomic(session, sku_id, warehouse_id, quantity):
        session.refresh(stock)
        raise BusinessError(
            INSUFFICIENT_STOCK,
            detail={
                "sku_id": sku_id,
                "warehouse_id": warehouse_id,
                "available": stock.available_qty,
                "requested": quantity,
            },
            http_status=409,
        )

    # The conditional UPDATE bypasses the ORM identity map, so re-read the row
    # to get the authoritative before/after values for the ledger.
    session.refresh(stock)

    return inventory_repo.append_transaction(
        session,
        sku_id=sku_id,
        warehouse_id=warehouse_id,
        type=InventoryTransactionType.ORDER_RESERVE,
        qty_delta=quantity,
        on_hand_before=stock.on_hand_qty,
        on_hand_after=stock.on_hand_qty,
        reserved_before=stock.reserved_qty - quantity,
        reserved_after=stock.reserved_qty,
        ref_type=ref_type,
        ref_id=ref_id,
        operator_id=operator_id,
        idempotency_key=idempotency_key,
        remark=remark,
    )


def release(
    session: Session,
    *,
    sku_id: int,
    warehouse_id: int,
    quantity: int,
    ref_type: str = "",
    ref_id: int | None = None,
    operator_id: int | None = None,
    idempotency_key: str | None = None,
    remark: str = "",
) -> InventoryTransaction:
    """Give occupied stock back, e.g. when an order is cancelled."""
    return _apply(
        session,
        sku_id=sku_id,
        warehouse_id=warehouse_id,
        type_=InventoryTransactionType.ORDER_RELEASE,
        reserved_delta=-abs(quantity),
        ref_type=ref_type,
        ref_id=ref_id,
        operator_id=operator_id,
        remark=remark,
        idempotency_key=idempotency_key,
    )


def outbound(
    session: Session,
    *,
    sku_id: int,
    warehouse_id: int,
    quantity: int,
    location_id: int | None = None,
    ref_type: str = "",
    ref_id: int | None = None,
    operator_id: int | None = None,
    remark: str = "",
    idempotency_key: str | None = None,
) -> InventoryTransaction:
    """Ship stock out: 实际库存与已占用**同时**减少。

    This is the step that turns a reservation into a real departure.  Both
    floors are enforced in one conditional UPDATE, so a row can never end up
    with negative on-hand or a reservation that outlived its stock.
    """
    if quantity <= 0:
        raise BusinessError(INVENTORY_ADJUST_ZERO_DELTA, "出库数量必须大于 0", http_status=400)

    if idempotency_key:
        existing = inventory_repo.get_transaction_by_idempotency(session, idempotency_key)
        if existing is not None:
            return existing

    stock = _lock_or_create(session, sku_id, warehouse_id)

    if not inventory_repo.try_outbound_atomic(session, sku_id, warehouse_id, quantity):
        session.refresh(stock)
        raise BusinessError(
            OUTBOUND_STOCK_MISMATCH,
            detail={
                "sku_id": sku_id,
                "warehouse_id": warehouse_id,
                "on_hand": stock.on_hand_qty,
                "reserved": stock.reserved_qty,
                "requested": quantity,
            },
            http_status=409,
        )

    session.refresh(stock)

    return inventory_repo.append_transaction(
        session,
        sku_id=sku_id,
        warehouse_id=warehouse_id,
        location_id=location_id,
        type=InventoryTransactionType.ORDER_OUTBOUND,
        qty_delta=-quantity,
        on_hand_before=stock.on_hand_qty + quantity,
        on_hand_after=stock.on_hand_qty,
        reserved_before=stock.reserved_qty + quantity,
        reserved_after=stock.reserved_qty,
        ref_type=ref_type,
        ref_id=ref_id,
        operator_id=operator_id,
        idempotency_key=idempotency_key,
        remark=remark,
    )


def set_stock_location(
    session: Session, *, sku_id: int, warehouse_id: int, location_id: int | None
) -> InventoryStock:
    """Assign (or clear) the standing pick location used to sort pick lists."""
    sku = product_repo.get_sku(session, sku_id)
    if sku is None:
        raise BusinessError(SKU_NOT_FOUND, detail={"sku_id": sku_id}, http_status=404)
    warehouse = warehouse_repo.get(session, warehouse_id)
    if warehouse is None:
        raise BusinessError(
            WAREHOUSE_NOT_FOUND, detail={"warehouse_id": warehouse_id}, http_status=404
        )

    if location_id is not None:
        location = warehouse_repo.get_location(session, location_id)
        # A location from another warehouse would produce a nonsensical pick route.
        if location is None or location.warehouse_id != warehouse_id:
            raise BusinessError(
                LOCATION_NOT_FOUND,
                detail={"location_id": location_id, "warehouse_id": warehouse_id},
                http_status=404,
            )

    stock = _lock_or_create(session, sku_id, warehouse_id, safety_qty=sku.safety_qty)
    inventory_repo.set_default_location(session, stock, location_id)
    session.commit()
    return stock


def receive_purchase(
    session: Session,
    *,
    sku_id: int,
    warehouse_id: int,
    qualified_qty: int = 0,
    defective_qty: int = 0,
    location_id: int | None = None,
    ref_type: str = "purchase_receipt",
    ref_id: int | None = None,
    operator_id: int | None = None,
    remark: str = "",
    idempotency_key: str | None = None,
) -> list[InventoryTransaction]:
    """采购到货的质检分流：合格进可售，次品进次品区。

    写两条独立流水，因为这是两笔不同的账面变化 —— 合格品提高可售，次品只进
    次品区、永远不参与可售。混成一条会让「实际库存」这个数字失去意义。
    """
    if qualified_qty < 0 or defective_qty < 0 or (qualified_qty + defective_qty) <= 0:
        raise BusinessError(RECEIPT_QUANTITY_INVALID, http_status=400)

    transactions: list[InventoryTransaction] = []
    if qualified_qty:
        transactions.append(
            _apply(
                session,
                sku_id=sku_id,
                warehouse_id=warehouse_id,
                type_=InventoryTransactionType.PURCHASE_INBOUND,
                qty_delta=qualified_qty,
                location_id=location_id,
                ref_type=ref_type,
                ref_id=ref_id,
                operator_id=operator_id,
                remark=remark,
                idempotency_key=f"{idempotency_key}:q" if idempotency_key else None,
                safety_qty=0,
            )
        )
    if defective_qty:
        transactions.append(
            _apply(
                session,
                sku_id=sku_id,
                warehouse_id=warehouse_id,
                # qty_delta 保持 0：实际库存没变，变的是次品区。
                type_=InventoryTransactionType.PURCHASE_DEFECTIVE,
                qty_delta=0,
                defective_delta=defective_qty,
                ref_type=ref_type,
                ref_id=ref_id,
                operator_id=operator_id,
                remark=remark or "采购到货次品",
                idempotency_key=f"{idempotency_key}:d" if idempotency_key else None,
            )
        )
    return transactions


def transfer_ship(
    session: Session,
    *,
    sku_id: int,
    from_warehouse_id: int,
    to_warehouse_id: int,
    quantity: int,
    ref_id: int | None = None,
    operator_id: int | None = None,
    remark: str = "",
    idempotency_key: str | None = None,
) -> list[InventoryTransaction]:
    """调拨发出。在两个仓库各写一条流水。

    在途记在**调入仓**（口径是「发往本仓的在途」）：调出仓实际库存减少，调入仓
    在途增加，可售两边都不受影响 —— 在途不可售这条规则在这里得到体现。
    """
    if quantity <= 0:
        raise BusinessError(TRANSFER_QUANTITY_INVALID, "调拨数量必须大于 0", http_status=400)

    out_tx = _apply(
        session,
        sku_id=sku_id,
        warehouse_id=from_warehouse_id,
        type_=InventoryTransactionType.TRANSFER_OUT,
        qty_delta=-quantity,
        ref_type="stock_transfer",
        ref_id=ref_id,
        operator_id=operator_id,
        remark=remark or "调拨发出",
        idempotency_key=f"{idempotency_key}:out" if idempotency_key else None,
    )
    in_transit_tx = _apply(
        session,
        sku_id=sku_id,
        warehouse_id=to_warehouse_id,
        type_=InventoryTransactionType.TRANSFER_OUT,
        qty_delta=0,
        in_transit_delta=quantity,
        ref_type="stock_transfer",
        ref_id=ref_id,
        operator_id=operator_id,
        remark=remark or "调入在途",
        idempotency_key=f"{idempotency_key}:transit" if idempotency_key else None,
    )
    return [out_tx, in_transit_tx]


def transfer_receive(
    session: Session,
    *,
    sku_id: int,
    to_warehouse_id: int,
    quantity: int,
    defective_qty: int = 0,
    ref_id: int | None = None,
    operator_id: int | None = None,
    remark: str = "",
    idempotency_key: str | None = None,
) -> InventoryTransaction:
    """调入仓收货：在途转为实际，次品单独入次品区。"""
    if quantity <= 0 or defective_qty < 0 or defective_qty > quantity:
        raise BusinessError(TRANSFER_QUANTITY_INVALID, http_status=400)

    return _apply(
        session,
        sku_id=sku_id,
        warehouse_id=to_warehouse_id,
        type_=InventoryTransactionType.TRANSFER_IN,
        qty_delta=quantity - defective_qty,
        in_transit_delta=-quantity,
        defective_delta=defective_qty,
        ref_type="stock_transfer",
        ref_id=ref_id,
        operator_id=operator_id,
        remark=remark or "调拨收货",
        idempotency_key=idempotency_key,
    )


def inbound(
    session: Session,
    *,
    sku_id: int,
    warehouse_id: int,
    quantity: int,
    type_: InventoryTransactionType = InventoryTransactionType.PURCHASE_INBOUND,
    ref_type: str = "",
    ref_id: int | None = None,
    operator_id: int | None = None,
    idempotency_key: str | None = None,
    remark: str = "",
    clear_in_transit: bool = False,
) -> InventoryTransaction:
    """Bring stock in (purchase receipt, return, transfer in, ...)."""
    return _apply(
        session,
        sku_id=sku_id,
        warehouse_id=warehouse_id,
        type_=type_,
        qty_delta=abs(quantity),
        in_transit_delta=-abs(quantity) if clear_in_transit else 0,
        ref_type=ref_type,
        ref_id=ref_id,
        operator_id=operator_id,
        remark=remark,
        idempotency_key=idempotency_key,
    )


# ------------------------------------------------------------------ read views
def to_stock_read(stock: InventoryStock) -> InventoryStockRead:
    sku = stock.sku
    warehouse = stock.warehouse
    return InventoryStockRead(
        id=stock.id,
        sku_id=stock.sku_id,
        sku_code=sku.sku_code if sku else "",
        sku_name=sku.display_name if sku else "",
        warehouse_id=stock.warehouse_id,
        warehouse_code=warehouse.code if warehouse else "",
        warehouse_name=warehouse.name if warehouse else "",
        on_hand_qty=stock.on_hand_qty,
        reserved_qty=stock.reserved_qty,
        in_transit_qty=stock.in_transit_qty,
        safety_qty=stock.safety_qty,
        defective_qty=stock.defective_qty,
        repair_qty=stock.repair_qty,
        # Derived, never stored; keeps every client showing the same number.
        available_qty=stock_formula.available_qty(
            stock.on_hand_qty, stock.reserved_qty, stock.safety_qty
        ),
        default_location_id=stock.default_location_id,
        default_location_code=stock.default_location.code if stock.default_location else "",
        version=stock.version,
        updated_at=stock.updated_at,
    )


def to_transaction_read(tx: InventoryTransaction) -> InventoryTransactionRead:
    operator = tx.operator
    return InventoryTransactionRead(
        id=tx.id,
        sku_id=tx.sku_id,
        sku_code=tx.sku.sku_code if tx.sku else "",
        warehouse_id=tx.warehouse_id,
        warehouse_code=tx.warehouse.code if tx.warehouse else "",
        location_id=tx.location_id,
        type=tx.type,
        qty_delta=tx.qty_delta,
        on_hand_before=tx.on_hand_before,
        on_hand_after=tx.on_hand_after,
        reserved_before=tx.reserved_before,
        reserved_after=tx.reserved_after,
        in_transit_before=tx.in_transit_before,
        in_transit_after=tx.in_transit_after,
        defective_before=tx.defective_before,
        defective_after=tx.defective_after,
        ref_type=tx.ref_type,
        ref_id=tx.ref_id,
        operator_id=tx.operator_id,
        operator_name=(operator.full_name or operator.username) if operator else "",
        remark=tx.remark,
        created_at=tx.created_at,
    )


def list_stock_reads(session: Session, page_result: PageResult) -> list[InventoryStockRead]:
    return [to_stock_read(stock) for stock in page_result.items]


def list_transaction_reads(
    session: Session, page_result: PageResult
) -> list[InventoryTransactionRead]:
    return [to_transaction_read(tx) for tx in page_result.items]


def parse_dt(value: str | None) -> dt.datetime | None:
    """Accept ``YYYY-MM-DD`` or a full ISO timestamp from query strings."""
    if not value:
        return None
    text = value.strip()
    try:
        if len(text) == 10:
            return dt.datetime.fromisoformat(text)
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None
