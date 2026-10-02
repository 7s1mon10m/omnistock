"""Data access for warehouses and their locations."""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.warehouse import Warehouse, WarehouseLocation
from app.utils.pagination import PageResult, paginate


def get(session: Session, warehouse_id: int) -> Warehouse | None:
    warehouse = session.get(Warehouse, warehouse_id)
    if warehouse is None or warehouse.deleted_at is not None:
        return None
    return warehouse


def get_by_code(session: Session, code: str) -> Warehouse | None:
    stmt = select(Warehouse).where(Warehouse.code == code, Warehouse.deleted_at.is_(None))
    return session.scalar(stmt)


def list_all(session: Session, *, active_only: bool = False) -> list[Warehouse]:
    stmt = select(Warehouse).where(Warehouse.deleted_at.is_(None))
    if active_only:
        stmt = stmt.where(Warehouse.is_active.is_(True))
    return list(session.scalars(stmt.order_by(Warehouse.id)).all())


def list_warehouses(
    session: Session,
    *,
    keyword: str | None = None,
    active_only: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    stmt = select(Warehouse).where(Warehouse.deleted_at.is_(None))
    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(or_(Warehouse.code.like(pattern), Warehouse.name.like(pattern)))
    if active_only:
        stmt = stmt.where(Warehouse.is_active.is_(True))
    stmt = stmt.order_by(Warehouse.id)
    return paginate(session, stmt, page, page_size)


def create(session: Session, **fields) -> Warehouse:
    warehouse = Warehouse(**fields)
    session.add(warehouse)
    session.flush()
    return warehouse


def count_locations(session: Session, warehouse_id: int) -> int:
    stmt = select(func.count()).select_from(WarehouseLocation).where(
        WarehouseLocation.warehouse_id == warehouse_id
    )
    return session.scalar(stmt) or 0


def list_locations(session: Session, warehouse_id: int, *, active_only: bool = False) -> list[WarehouseLocation]:
    stmt = select(WarehouseLocation).where(WarehouseLocation.warehouse_id == warehouse_id)
    if active_only:
        stmt = stmt.where(WarehouseLocation.is_active.is_(True))
    return list(session.scalars(stmt.order_by(WarehouseLocation.code)).all())


def get_location(session: Session, location_id: int) -> WarehouseLocation | None:
    return session.get(WarehouseLocation, location_id)


def get_location_by_code(session: Session, warehouse_id: int, code: str) -> WarehouseLocation | None:
    stmt = select(WarehouseLocation).where(
        WarehouseLocation.warehouse_id == warehouse_id, WarehouseLocation.code == code
    )
    return session.scalar(stmt)


def create_location(session: Session, **fields) -> WarehouseLocation:
    location = WarehouseLocation(**fields)
    session.add(location)
    session.flush()
    return location
