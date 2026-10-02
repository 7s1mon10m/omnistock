"""Product services: SPU / SKU / barcode maintenance."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import (
    BARCODE_DUPLICATE,
    BusinessError,
    SKU_CODE_DUPLICATE,
    SKU_NOT_FOUND,
    SPU_CODE_DUPLICATE,
    SPU_NOT_FOUND,
)
from app.models.product import Sku, SkuBarcode, SkuStatus, Spu, SpuStatus
from app.repositories import inventory_repo, product_repo, warehouse_repo
from app.schemas.product import (
    BarcodeCreate,
    BarcodeRead,
    SkuCreate,
    SkuRead,
    SkuUpdate,
    SpuCreate,
    SpuRead,
    SpuUpdate,
)
from app.utils.pagination import PageResult


# ------------------------------------------------------------------------ SPU
def get_spu_or_404(session: Session, spu_id: int) -> Spu:
    spu = product_repo.get_spu(session, spu_id)
    if spu is None:
        raise BusinessError(SPU_NOT_FOUND, http_status=404)
    return spu


def create_spu(session: Session, payload: SpuCreate) -> Spu:
    if product_repo.get_spu_by_code(session, payload.code) is not None:
        raise BusinessError(SPU_CODE_DUPLICATE, http_status=409)
    spu = product_repo.create_spu(session, **payload.model_dump())
    session.commit()
    return spu


def update_spu(session: Session, spu: Spu, payload: SpuUpdate) -> Spu:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(spu, field, value)
    session.commit()
    return spu


def to_spu_read(session: Session, spu: Spu) -> SpuRead:
    return SpuRead(
        id=spu.id,
        code=spu.code,
        name=spu.name,
        category=spu.category,
        brand=spu.brand,
        type=spu.type,
        images=list(spu.images or []),
        description=spu.description,
        status=spu.status,
        sku_count=product_repo.count_skus(session, spu.id),
        created_at=spu.created_at,
    )


# ------------------------------------------------------------------------ SKU
def get_sku_or_404(session: Session, sku_id: int) -> Sku:
    sku = product_repo.get_sku(session, sku_id)
    if sku is None:
        raise BusinessError(SKU_NOT_FOUND, http_status=404)
    return sku


def _generate_sku_code(session: Session, spu: Spu, spec: dict) -> str:
    """``SKU-<spu code>-<spec suffix>`` when the spec is ASCII, else a序号.

    Spec values are often Chinese ("白色 / L 码"), which makes for an ugly and
    hard-to-scan SKU code, so in that case we fall back to a running number.
    Callers who want a specific code simply pass ``sku_code`` explicitly.
    """
    suffix_parts: list[str] = []
    ascii_ok = bool(spec)
    for value in spec.values():
        text = str(value).strip()
        if not text:
            ascii_ok = False
            break
        token = text.upper().replace(" ", "")
        if not token.isascii() or not token.isalnum():
            ascii_ok = False
            break
        suffix_parts.append(token)

    if ascii_ok and suffix_parts:
        candidate = f"{settings.SKU_CODE_PREFIX}-{spu.code}-{'-'.join(suffix_parts)}"
        if product_repo.get_sku_by_code(session, candidate) is None:
            return candidate

    seq = product_repo.count_skus_with_prefix(session, f"{settings.SKU_CODE_PREFIX}-{spu.code}-") + 1
    while True:
        candidate = f"{settings.SKU_CODE_PREFIX}-{spu.code}-{seq:02d}"
        if product_repo.get_sku_by_code(session, candidate) is None:
            return candidate
        seq += 1


def _assert_barcode_free(session: Session, barcode: str | None, *, exclude_sku_id: int | None = None) -> None:
    if not barcode:
        return
    owner = product_repo.get_sku_by_barcode(session, barcode)
    if owner is not None and owner.id != exclude_sku_id:
        raise BusinessError(
            BARCODE_DUPLICATE, detail={"barcode": barcode, "sku_id": owner.id}, http_status=409
        )
    extra = product_repo.get_barcode(session, barcode)
    if extra is not None and extra.sku_id != exclude_sku_id:
        raise BusinessError(
            BARCODE_DUPLICATE, detail={"barcode": barcode, "sku_id": extra.sku_id}, http_status=409
        )


def create_sku(session: Session, spu_id: int, payload: SkuCreate) -> Sku:
    spu = get_spu_or_404(session, spu_id)

    sku_code = (payload.sku_code or "").strip() or _generate_sku_code(session, spu, payload.spec_json)
    if product_repo.get_sku_by_code(session, sku_code) is not None:
        raise BusinessError(
            SKU_CODE_DUPLICATE, detail={"sku_code": sku_code}, http_status=409
        )
    _assert_barcode_free(session, payload.barcode)

    sku = product_repo.create_sku(
        session,
        spu_id=spu.id,
        sku_code=sku_code,
        spec_json=payload.spec_json or {},
        barcode=(payload.barcode or None),
        weight_g=payload.weight_g,
        package_spec=payload.package_spec,
        purchase_price_cents=payload.purchase_price_cents,
        default_supplier_id=payload.default_supplier_id,
        safety_qty=payload.safety_qty,
    )

    # Give the new SKU a zero row in every active warehouse so the inventory
    # screen shows it everywhere from day one.
    for warehouse in warehouse_repo.list_all(session, active_only=True):
        inventory_repo.create_stock(
            session, sku_id=sku.id, warehouse_id=warehouse.id, safety_qty=sku.safety_qty
        )

    if payload.barcode:
        product_repo.create_barcode(
            session, sku_id=sku.id, barcode=payload.barcode, is_primary=True, remark="primary"
        )

    session.commit()
    return sku


def update_sku(session: Session, sku: Sku, payload: SkuUpdate) -> Sku:
    changes = payload.model_dump(exclude_unset=True)
    if "status" in changes and changes["status"] is not None:
        if changes["status"] not in (SkuStatus.ACTIVE, SkuStatus.ARCHIVED):
            raise BusinessError(40012, http_status=400)
    for field, value in changes.items():
        setattr(sku, field, value)

    # A safety-stock change flows into today's sellable number immediately.
    if "safety_qty" in changes and changes["safety_qty"] is not None:
        for stock in inventory_repo.list_stocks(session, sku_id=sku.id, page_size=200).items:
            stock.safety_qty = sku.safety_qty
    session.commit()
    return sku


def to_sku_read(sku: Sku) -> SkuRead:
    return SkuRead(
        id=sku.id,
        spu_id=sku.spu_id,
        sku_code=sku.sku_code,
        display_name=sku.display_name,
        spec_json=dict(sku.spec_json or {}),
        barcode=sku.barcode,
        weight_g=sku.weight_g,
        package_spec=sku.package_spec,
        purchase_price_cents=sku.purchase_price_cents,
        default_supplier_id=sku.default_supplier_id,
        safety_qty=sku.safety_qty,
        status=sku.status,
        is_bundle=bool(sku.components),
        created_at=sku.created_at,
    )


# ------------------------------------------------------------------- barcodes
def add_barcode(session: Session, sku_id: int, payload: BarcodeCreate) -> SkuBarcode:
    sku = get_sku_or_404(session, sku_id)
    _assert_barcode_free(session, payload.barcode, exclude_sku_id=sku.id)
    row = product_repo.create_barcode(
        session,
        sku_id=sku.id,
        barcode=payload.barcode,
        is_primary=payload.is_primary,
        remark=payload.remark,
    )
    if payload.is_primary:
        sku.barcode = payload.barcode
    session.commit()
    return row


def delete_barcode(session: Session, sku_id: int, barcode_id: int) -> None:
    rows = product_repo.list_barcodes(session, sku_id)
    target = next((row for row in rows if row.id == barcode_id), None)
    if target is None:
        raise BusinessError(40415, "条码不存在", http_status=404)
    product_repo.delete_barcode(session, target)
    session.commit()


def to_barcode_read(row: SkuBarcode) -> BarcodeRead:
    return BarcodeRead(
        id=row.id,
        sku_id=row.sku_id,
        barcode=row.barcode,
        is_primary=row.is_primary,
        remark=row.remark,
    )


def resolve_barcode(session: Session, barcode: str) -> Sku:
    """Find the SKU a scanned code belongs to (primary or extra barcode)."""
    sku = product_repo.get_sku_by_barcode(session, barcode)
    if sku is not None:
        return sku
    extra = product_repo.get_barcode(session, barcode)
    if extra is not None:
        return get_sku_or_404(session, extra.sku_id)
    raise BusinessError(SKU_NOT_FOUND, detail={"barcode": barcode}, http_status=404)


def list_spu_page(session: Session, page_result: PageResult) -> list[SpuRead]:
    return [to_spu_read(session, spu) for spu in page_result.items]


def list_sku_page(session: Session, page_result: PageResult) -> list[SkuRead]:
    return [to_sku_read(sku) for sku in page_result.items]
