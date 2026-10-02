"""Warehouse and location services."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import (
    BusinessError,
    LOCATION_CODE_DUPLICATE,
    WAREHOUSE_CODE_DUPLICATE,
    WAREHOUSE_NOT_FOUND,
)
from app.models.warehouse import Warehouse
from app.repositories import warehouse_repo
from app.schemas.warehouse import (
    LocationCreate,
    LocationRead,
    WarehouseCreate,
    WarehouseRead,
    WarehouseUpdate,
)


def get_warehouse_or_404(session: Session, warehouse_id: int) -> Warehouse:
    warehouse = warehouse_repo.get(session, warehouse_id)
    if warehouse is None:
        raise BusinessError(WAREHOUSE_NOT_FOUND, http_status=404)
    return warehouse


def _next_code(session: Session, prefix: str = "WH") -> str:
    existing = {w.code for w in warehouse_repo.list_all(session)}
    seq = len(existing) + 1
    while f"{prefix}-{seq:03d}" in existing:
        seq += 1
    return f"{prefix}-{seq:03d}"


def create_warehouse(session: Session, payload: WarehouseCreate) -> Warehouse:
    code = (payload.code or "").strip() or _next_code(session)
    if warehouse_repo.get_by_code(session, code) is not None:
        raise BusinessError(WAREHOUSE_CODE_DUPLICATE, detail={"code": code}, http_status=409)

    data = payload.model_dump()
    data["code"] = code
    warehouse = warehouse_repo.create(session, **data)
    session.commit()
    return warehouse


def update_warehouse(session: Session, warehouse: Warehouse, payload: WarehouseUpdate) -> Warehouse:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(warehouse, field, value)
    session.commit()
    return warehouse


def ensure_default_warehouse(session: Session) -> Warehouse:
    """Guarantee the head-office warehouse exists (used by seed + first start)."""
    existing = warehouse_repo.get_by_code(session, settings.DEFAULT_WAREHOUSE_CODE)
    if existing is not None:
        return existing
    return warehouse_repo.create(
        session,
        code=settings.DEFAULT_WAREHOUSE_CODE,
        name=settings.DEFAULT_WAREHOUSE_NAME,
        remark="系统初始化创建",
    )


def to_warehouse_read(session: Session, warehouse: Warehouse) -> WarehouseRead:
    return WarehouseRead(
        id=warehouse.id,
        code=warehouse.code,
        name=warehouse.name,
        type=warehouse.type,
        address=warehouse.address,
        contact_name=warehouse.contact_name,
        contact_phone=warehouse.contact_phone,
        is_active=warehouse.is_active,
        remark=warehouse.remark,
        location_count=warehouse_repo.count_locations(session, warehouse.id),
        created_at=warehouse.created_at,
    )


def list_warehouse_reads(session: Session, page_result) -> list[WarehouseRead]:
    return [to_warehouse_read(session, w) for w in page_result.items]


def to_location_read(location) -> LocationRead:
    return LocationRead(
        id=location.id,
        warehouse_id=location.warehouse_id,
        code=location.code,
        name=location.name,
        zone=location.zone,
        is_active=location.is_active,
    )


def list_locations(session: Session, warehouse_id: int, *, active_only: bool = False):
    get_warehouse_or_404(session, warehouse_id)
    return warehouse_repo.list_locations(session, warehouse_id, active_only=active_only)


def create_location(session: Session, warehouse_id: int, payload: LocationCreate):
    get_warehouse_or_404(session, warehouse_id)
    if warehouse_repo.get_location_by_code(session, warehouse_id, payload.code) is not None:
        raise BusinessError(
            LOCATION_CODE_DUPLICATE,
            detail={"code": payload.code, "warehouse_id": warehouse_id},
            http_status=409,
        )
    location = warehouse_repo.create_location(
        session,
        warehouse_id=warehouse_id,
        code=payload.code,
        name=payload.name,
        zone=payload.zone,
        is_active=payload.is_active,
    )
    session.commit()
    return location
