"""Supplier endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.v1.guards import BuyerGuard, ViewerGuard
from app.core.deps import DbSession
from app.repositories import supplier_repo
from app.schemas.common import Page
from app.schemas.supplier import SupplierCreate, SupplierRead, SupplierUpdate
from app.services import supplier_service

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.get("", response_model=Page[SupplierRead], summary="供应商列表")
def list_suppliers(
    session: DbSession,
    _: ViewerGuard,
    keyword: str | None = None,
    is_active: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Page[SupplierRead]:
    result = supplier_repo.list_suppliers(
        session, keyword=keyword, is_active=is_active, page=page, page_size=page_size
    )
    return Page(
        items=supplier_service.list_reads(session, result),
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post("", response_model=SupplierRead, status_code=201, summary="新建供应商")
def create_supplier(payload: SupplierCreate, session: DbSession, _: BuyerGuard) -> SupplierRead:
    supplier = supplier_service.create(session, payload)
    return supplier_service.to_read(session, supplier)


@router.get("/{supplier_id}", response_model=SupplierRead, summary="供应商详情")
def get_supplier(supplier_id: int, session: DbSession, _: ViewerGuard) -> SupplierRead:
    supplier = supplier_service.get_or_404(session, supplier_id)
    return supplier_service.to_read(session, supplier)


@router.patch("/{supplier_id}", response_model=SupplierRead, summary="更新供应商")
def update_supplier(
    supplier_id: int, payload: SupplierUpdate, session: DbSession, _: BuyerGuard
) -> SupplierRead:
    supplier = supplier_service.get_or_404(session, supplier_id)
    supplier = supplier_service.update(session, supplier, payload)
    return supplier_service.to_read(session, supplier)
