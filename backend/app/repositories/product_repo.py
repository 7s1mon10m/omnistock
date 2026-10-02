"""Data access for SPU, SKU, barcodes and bundles."""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.product import (
    BundleComponent,
    Sku,
    SkuBarcode,
    SkuStatus,
    Spu,
    SpuStatus,
    SpuType,
)
from app.utils.pagination import PageResult, paginate

# ------------------------------------------------------------------------ SPU


def get_spu(session: Session, spu_id: int) -> Spu | None:
    spu = session.get(Spu, spu_id)
    if spu is None or spu.deleted_at is not None:
        return None
    return spu


def get_spu_by_code(session: Session, code: str) -> Spu | None:
    stmt = select(Spu).where(Spu.code == code, Spu.deleted_at.is_(None))
    return session.scalar(stmt)


def list_spus(
    session: Session,
    *,
    keyword: str | None = None,
    status: SpuStatus | None = None,
    type_: SpuType | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    stmt = select(Spu).where(Spu.deleted_at.is_(None))
    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(or_(Spu.code.like(pattern), Spu.name.like(pattern)))
    if status:
        stmt = stmt.where(Spu.status == status)
    if type_:
        stmt = stmt.where(Spu.type == type_)
    stmt = stmt.order_by(Spu.id.desc())
    return paginate(session, stmt, page, page_size)


def create_spu(session: Session, **fields) -> Spu:
    spu = Spu(**fields)
    session.add(spu)
    session.flush()
    return spu


def count_skus(session: Session, spu_id: int) -> int:
    stmt = select(func.count()).select_from(Sku).where(
        Sku.spu_id == spu_id, Sku.deleted_at.is_(None)
    )
    return session.scalar(stmt) or 0


# ------------------------------------------------------------------------ SKU


def get_sku(session: Session, sku_id: int) -> Sku | None:
    sku = session.get(Sku, sku_id)
    if sku is None or sku.deleted_at is not None:
        return None
    return sku


def get_sku_by_code(session: Session, sku_code: str) -> Sku | None:
    stmt = select(Sku).where(Sku.sku_code == sku_code, Sku.deleted_at.is_(None))
    return session.scalar(stmt)


def get_sku_by_barcode(session: Session, barcode: str) -> Sku | None:
    stmt = select(Sku).where(Sku.barcode == barcode, Sku.deleted_at.is_(None))
    return session.scalar(stmt)


def list_skus(
    session: Session,
    *,
    spu_id: int | None = None,
    keyword: str | None = None,
    status: SkuStatus | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    stmt = (
        select(Sku)
        .options(selectinload(Sku.spu), selectinload(Sku.components))
        .join(Spu, Sku.spu_id == Spu.id)
        .where(Sku.deleted_at.is_(None))
    )
    if spu_id:
        stmt = stmt.where(Sku.spu_id == spu_id)
    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(
            or_(Sku.sku_code.like(pattern), Sku.barcode.like(pattern), Spu.name.like(pattern))
        )
    if status:
        stmt = stmt.where(Sku.status == status)
    stmt = stmt.order_by(Sku.id.desc())
    return paginate(session, stmt, page, page_size)


def create_sku(session: Session, **fields) -> Sku:
    sku = Sku(**fields)
    session.add(sku)
    session.flush()
    return sku


def count_skus_with_prefix(session: Session, prefix: str) -> int:
    stmt = select(func.count()).select_from(Sku).where(Sku.sku_code.like(f"{prefix}%"))
    return session.scalar(stmt) or 0


# -------------------------------------------------------------------- barcodes


def get_barcode(session: Session, barcode: str) -> SkuBarcode | None:
    return session.scalar(select(SkuBarcode).where(SkuBarcode.barcode == barcode))


def list_barcodes(session: Session, sku_id: int) -> list[SkuBarcode]:
    return list(
        session.scalars(
            select(SkuBarcode).where(SkuBarcode.sku_id == sku_id).order_by(SkuBarcode.id)
        ).all()
    )


def create_barcode(session: Session, **fields) -> SkuBarcode:
    row = SkuBarcode(**fields)
    session.add(row)
    session.flush()
    return row


def delete_barcode(session: Session, row: SkuBarcode) -> None:
    session.delete(row)
    session.flush()


# --------------------------------------------------------------------- bundles


def list_components(session: Session, bundle_sku_id: int) -> list[BundleComponent]:
    stmt = (
        select(BundleComponent)
        .options(selectinload(BundleComponent.component_sku).selectinload(Sku.spu))
        .where(BundleComponent.bundle_sku_id == bundle_sku_id)
        .order_by(BundleComponent.id)
    )
    return list(session.scalars(stmt).all())


def replace_components(
    session: Session, bundle_sku_id: int, rows: list[dict]
) -> list[BundleComponent]:
    """Replace the component list of a bundle in one transaction."""
    for existing in session.scalars(
        select(BundleComponent).where(BundleComponent.bundle_sku_id == bundle_sku_id)
    ).all():
        session.delete(existing)
    session.flush()

    created: list[BundleComponent] = []
    for row in rows:
        item = BundleComponent(bundle_sku_id=bundle_sku_id, **row)
        session.add(item)
        created.append(item)
    session.flush()
    return created


def is_used_as_component(session: Session, sku_id: int) -> bool:
    stmt = select(func.count()).select_from(BundleComponent).where(
        BundleComponent.component_sku_id == sku_id
    )
    return (session.scalar(stmt) or 0) > 0
