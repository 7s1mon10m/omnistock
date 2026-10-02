"""Warehouse and location endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.v1.guards import AdminGuard, ViewerGuard
from app.core.deps import DbSession
from app.schemas.common import Page
from app.schemas.warehouse import (
    LocationCreate,
    LocationRead,
    WarehouseCreate,
    WarehouseRead,
    WarehouseUpdate,
)
from app.services import warehouse_service
from app.repositories import warehouse_repo

router = APIRouter(prefix="/warehouses", tags=["warehouses"])


@router.get("", response_model=Page[WarehouseRead], summary="仓库列表")
def list_warehouses(
    session: DbSession,
    _: ViewerGuard,
    keyword: str | None = None,
    active_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Page[WarehouseRead]:
    result = warehouse_repo.list_warehouses(
        session, keyword=keyword, active_only=active_only, page=page, page_size=page_size
    )
    return Page(
        items=warehouse_service.list_warehouse_reads(session, result),
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post("", response_model=WarehouseRead, status_code=201, summary="新建仓库")
def create_warehouse(payload: WarehouseCreate, session: DbSession, _: AdminGuard) -> WarehouseRead:
    warehouse = warehouse_service.create_warehouse(session, payload)
    return warehouse_service.to_warehouse_read(session, warehouse)


@router.get("/{warehouse_id}", response_model=WarehouseRead, summary="仓库详情")
def get_warehouse(warehouse_id: int, session: DbSession, _: ViewerGuard) -> WarehouseRead:
    warehouse = warehouse_service.get_warehouse_or_404(session, warehouse_id)
    return warehouse_service.to_warehouse_read(session, warehouse)


@router.patch("/{warehouse_id}", response_model=WarehouseRead, summary="更新仓库")
def update_warehouse(
    warehouse_id: int, payload: WarehouseUpdate, session: DbSession, _: AdminGuard
) -> WarehouseRead:
    warehouse = warehouse_service.get_warehouse_or_404(session, warehouse_id)
    warehouse = warehouse_service.update_warehouse(session, warehouse, payload)
    return warehouse_service.to_warehouse_read(session, warehouse)


@router.get(
    "/{warehouse_id}/locations", response_model=list[LocationRead], summary="库位列表"
)
def list_locations(
    warehouse_id: int, session: DbSession, _: ViewerGuard, active_only: bool = False
) -> list[LocationRead]:
    locations = warehouse_service.list_locations(session, warehouse_id, active_only=active_only)
    return [warehouse_service.to_location_read(loc) for loc in locations]


@router.post(
    "/{warehouse_id}/locations",
    response_model=LocationRead,
    status_code=201,
    summary="新建库位",
)
def create_location(
    warehouse_id: int, payload: LocationCreate, session: DbSession, _: AdminGuard
) -> LocationRead:
    location = warehouse_service.create_location(session, warehouse_id, payload)
    return warehouse_service.to_location_read(location)
