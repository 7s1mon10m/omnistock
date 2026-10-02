"""Supplier services."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import SUPPLIER_CODE_DUPLICATE, SUPPLIER_NOT_FOUND, BusinessError
from app.models.supplier import Supplier
from app.repositories import supplier_repo
from app.schemas.supplier import SupplierCreate, SupplierRead, SupplierUpdate


def get_or_404(session: Session, supplier_id: int) -> Supplier:
    supplier = supplier_repo.get(session, supplier_id)
    if supplier is None:
        raise BusinessError(SUPPLIER_NOT_FOUND, http_status=404)
    return supplier


def _next_code(session: Session) -> str:
    """``SUP001``, ``SUP002``… skipping anything already taken."""
    seq = supplier_repo.count_all(session) + 1
    while True:
        candidate = f"{settings.SUPPLIER_CODE_PREFIX}{seq:03d}"
        if supplier_repo.get_by_code(session, candidate) is None:
            return candidate
        seq += 1


def create(session: Session, payload: SupplierCreate) -> Supplier:
    data = payload.model_dump()
    code = (data.pop("code") or "").strip()
    if code:
        if supplier_repo.get_by_code(session, code) is not None:
            raise BusinessError(
                SUPPLIER_CODE_DUPLICATE, detail={"code": code}, http_status=409
            )
    else:
        code = _next_code(session)

    supplier = supplier_repo.create(session, code=code, **data)
    session.commit()
    return supplier


def update(session: Session, supplier: Supplier, payload: SupplierUpdate) -> Supplier:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(supplier, field, value)
    session.commit()
    return supplier


def to_read(session: Session, supplier: Supplier) -> SupplierRead:
    return SupplierRead(
        id=supplier.id,
        code=supplier.code,
        name=supplier.name,
        contact_name=supplier.contact_name,
        contact_phone=supplier.contact_phone,
        email=supplier.email,
        address=supplier.address,
        payment_terms=supplier.payment_terms,
        lead_time_days=supplier.lead_time_days,
        is_active=supplier.is_active,
        remark=supplier.remark,
        open_order_count=supplier_repo.count_open_orders(session, supplier.id),
        created_at=supplier.created_at,
    )


def list_reads(session: Session, page_result) -> list[SupplierRead]:
    return [to_read(session, supplier) for supplier in page_result.items]
