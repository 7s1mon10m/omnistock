"""Bundle (组合商品) rules.

A bundle is just a SKU whose SPU is of type ``bundle`` and which has component
rows.  It owns no stock: reserving a bundle reserves each component SKU.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import (
    BUNDLE_CANNOT_NEST,
    BUNDLE_COMPONENT_INVALID,
    INSUFFICIENT_STOCK,
    SKU_NOT_FOUND,
    SPU_TYPE_NOT_BUNDLE,
    BusinessError,
)
from app.domain import bundle_math, stock_formula
from app.models.inventory import InventoryTransaction
from app.models.product import BundleComponent, Sku, SpuType
from app.repositories import inventory_repo, product_repo
from app.schemas.product import BundleComponentRead, BundleRead, BundleSetRequest
from app.services import inventory_service


def get_bundle_or_404(session: Session, bundle_sku_id: int) -> Sku:
    sku = product_repo.get_sku(session, bundle_sku_id)
    if sku is None:
        raise BusinessError(SKU_NOT_FOUND, http_status=404)
    return sku


def set_components(
    session: Session, bundle_sku_id: int, payload: BundleSetRequest
) -> list[BundleComponent]:
    """Replace the component list of a bundle SKU."""
    bundle = get_bundle_or_404(session, bundle_sku_id)

    if bundle.spu is None or bundle.spu.type != SpuType.BUNDLE:
        raise BusinessError(SPU_TYPE_NOT_BUNDLE, http_status=400)

    rows: list[dict] = []
    seen: set[int] = set()
    for item in payload.components:
        if item.component_sku_id == bundle_sku_id:
            raise BusinessError(
                BUNDLE_COMPONENT_INVALID, "组合商品不能把自己作为子项", http_status=409
            )
        component = product_repo.get_sku(session, item.component_sku_id)
        if component is None:
            raise BusinessError(
                BUNDLE_COMPONENT_INVALID,
                detail={"component_sku_id": item.component_sku_id, "reason": "not_found"},
                http_status=409,
            )
        # No nesting: a component must be a plain SKU, not another bundle.
        if product_repo.list_components(session, component.id):
            raise BusinessError(
                BUNDLE_CANNOT_NEST,
                detail={"component_sku_id": component.id},
                http_status=400,
            )
        if component.id in seen:
            raise BusinessError(
                BUNDLE_COMPONENT_INVALID,
                detail={"component_sku_id": component.id, "reason": "duplicate"},
                http_status=409,
            )
        seen.add(component.id)
        rows.append({"component_sku_id": component.id, "quantity": item.quantity})

    components = product_repo.replace_components(session, bundle_sku_id, rows)
    session.commit()
    return components


def component_pairs(session: Session, bundle_sku_id: int) -> list[tuple[int, int]]:
    """``[(component_sku_id, per_bundle_qty), ...]`` for a bundle."""
    return [
        (row.component_sku_id, row.quantity)
        for row in product_repo.list_components(session, bundle_sku_id)
    ]


def explode(session: Session, bundle_sku_id: int, quantity: int) -> list[tuple[int, int]]:
    """Expand ``quantity`` bundles into required component quantities."""
    pairs = component_pairs(session, bundle_sku_id)
    if not pairs:
        raise BusinessError(
            BUNDLE_COMPONENT_INVALID, "组合商品尚未配置子项", http_status=409
        )
    return bundle_math.explode(pairs, quantity)


def to_bundle_read(
    session: Session, bundle_sku_id: int, warehouse_id: int | None = None
) -> BundleRead:
    bundle = get_bundle_or_404(session, bundle_sku_id)
    components: list[BundleComponentRead] = []
    availability: list[tuple[int, int]] = []

    for row in product_repo.list_components(session, bundle_sku_id):
        component = row.component_sku
        available = 0
        if warehouse_id:
            available = inventory_service.available_for(session, component.id, warehouse_id)
        components.append(
            BundleComponentRead(
                component_sku_id=component.id,
                component_sku_code=component.sku_code,
                component_name=component.display_name,
                quantity=row.quantity,
                available_qty=available,
            )
        )
        availability.append((available, row.quantity))

    return BundleRead(
        bundle_sku_id=bundle.id,
        bundle_sku_code=bundle.sku_code,
        bundle_name=bundle.display_name,
        components=components,
        buildable_qty=stock_formula.buildable_bundles(availability) if warehouse_id else 0,
    )


def reserve_bundle(
    session: Session,
    *,
    bundle_sku_id: int,
    warehouse_id: int,
    quantity: int,
    ref_type: str = "",
    ref_id: int | None = None,
    operator_id: int | None = None,
    idempotency_key: str | None = None,
) -> list[InventoryTransaction]:
    """Reserve every component of a bundle, all-or-nothing.

    The cheap pre-check below turns the common shortage into one clear error;
    the per-component reserve then holds the row lock.  A failure anywhere
    leaves the caller's transaction uncommitted, so nothing is half-booked.
    """
    required = explode(session, bundle_sku_id, quantity)

    shortages = [
        {"sku_id": sku_id, "required": need,
         "available": inventory_service.available_for(session, sku_id, warehouse_id)}
        for sku_id, need in required
        if inventory_service.available_for(session, sku_id, warehouse_id) < need
    ]
    if shortages:
        raise BusinessError(INSUFFICIENT_STOCK, detail={"shortages": shortages}, http_status=409)

    transactions: list[InventoryTransaction] = []
    try:
        for sku_id, need in required:
            transactions.append(
                inventory_service.reserve(
                    session,
                    sku_id=sku_id,
                    warehouse_id=warehouse_id,
                    quantity=need,
                    ref_type=ref_type or "bundle",
                    ref_id=ref_id,
                    operator_id=operator_id,
                    idempotency_key=f"{idempotency_key}:{sku_id}" if idempotency_key else None,
                )
            )
    except Exception:
        # All-or-nothing: a bundle reservation must never leave half its
        # components occupied.
        session.rollback()
        raise
    return transactions


def bundle_sellable(session: Session, bundle_sku_id: int, warehouse_id: int) -> int:
    """How many complete bundles could be reserved right now."""
    pairs = component_pairs(session, bundle_sku_id)
    availability = [
        (inventory_service.available_for(session, sku_id, warehouse_id), per_bundle)
        for sku_id, per_bundle in pairs
    ]
    return stock_formula.buildable_bundles(availability)
