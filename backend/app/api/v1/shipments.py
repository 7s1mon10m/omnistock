"""Fulfilment endpoints: build a pick list, scan it, pack it, ship it.

The pick list is sorted by warehouse location, so a picker walks the aisles in
order instead of zig-zagging.  Scanning is validated against the list — a wrong
item is refused on the spot rather than discovered by the customer.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.v1.guards import FulfillmentGuard, ViewerGuard, WarehouseGuard
from app.core.deps import DbSession
from app.models.shipment import PickResult, ShipmentStatus
from app.repositories import shipment_repo
from app.schemas.common import Page
from app.schemas.shipment import (
    CancelShipmentRequest,
    ClaimRequest,
    OutboundLine,
    PackRequest,
    PickManualRequest,
    PickRecordRead,
    PickRequest,
    PickResultRead,
    ShipmentActionResult,
    ShipmentCreate,
    ShipmentListRead,
    ShipmentRead,
    ShipRequest,
)
from app.services import order_service, shipment_service

router = APIRouter(prefix="/shipments", tags=["shipments"])


@router.get("", response_model=Page[ShipmentListRead], summary="发货单列表")
def list_shipments(
    session: DbSession,
    _: ViewerGuard,
    status: ShipmentStatus | None = None,
    warehouse_id: int | None = None,
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Page[ShipmentListRead]:
    result = shipment_repo.list_shipments(
        session,
        status=status,
        warehouse_id=warehouse_id,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[shipment_service.to_list_read(session, row) for row in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post("", response_model=ShipmentRead, status_code=201, summary="由订单生成发货单")
def create_shipment(
    payload: ShipmentCreate, session: DbSession, user: FulfillmentGuard
) -> ShipmentRead:
    order = order_service.get_order_or_404(session, payload.order_id)
    shipment = shipment_service.create_shipment(
        session, order, remark=payload.remark, operator_id=user.id
    )
    return shipment_service.to_shipment_read(session, shipment)


@router.get("/{shipment_id}", response_model=ShipmentRead, summary="发货单详情（拣货单）")
def get_shipment(shipment_id: int, session: DbSession, _: ViewerGuard) -> ShipmentRead:
    shipment = shipment_service.get_shipment_or_404(session, shipment_id)
    return shipment_service.to_shipment_read(session, shipment)


@router.get(
    "/{shipment_id}/pick-records",
    response_model=Page[PickRecordRead],
    summary="扫码拣货记录（含被拦截的）",
)
def list_pick_records(
    shipment_id: int,
    session: DbSession,
    _: ViewerGuard,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> Page[PickRecordRead]:
    shipment_service.get_shipment_or_404(session, shipment_id)
    result = shipment_repo.list_pick_records(
        session, shipment_id=shipment_id, page=page, page_size=page_size
    )
    return Page(
        items=[shipment_service.to_pick_record_read(row) for row in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post("/{shipment_id}/claim", response_model=ShipmentRead, summary="领取拣货任务")
def claim(
    shipment_id: int, payload: ClaimRequest, session: DbSession, user: WarehouseGuard
) -> ShipmentRead:
    shipment = shipment_service.get_shipment_or_404(session, shipment_id)
    shipment = shipment_service.claim(
        session, shipment, picker_id=payload.picker_id, operator_id=user.id
    )
    return shipment_service.to_shipment_read(session, shipment)


@router.post(
    "/{shipment_id}/pick",
    response_model=PickResultRead,
    summary="扫码拣货（校验不一致会拦截）",
)
def pick(
    shipment_id: int, payload: PickRequest, session: DbSession, user: WarehouseGuard
) -> PickResultRead:
    shipment = shipment_service.get_shipment_or_404(session, shipment_id)
    record = shipment_service.pick(
        session,
        shipment,
        barcode=payload.barcode,
        quantity=payload.quantity,
        operator_id=user.id,
    )
    session.refresh(shipment)
    item = next(
        (row for row in shipment.items if row.id == record.shipment_item_id), None
    )
    return PickResultRead(
        accepted=record.accepted,
        result=record.result,
        message=record.message,
        shipment_id=shipment.id,
        shipment_item_id=record.shipment_item_id,
        sku_id=record.sku_id,
        sku_code=record.sku.sku_code if record.sku else "",
        picked_qty=item.picked_qty if item else 0,
        quantity=item.quantity if item else 0,
        shipment_status=shipment.status,
        progress=shipment.progress,
    )


@router.post(
    "/{shipment_id}/pick-manual", response_model=PickResultRead, summary="手工确认拣货（无条码）"
)
def pick_manual(
    shipment_id: int, payload: PickManualRequest, session: DbSession, user: WarehouseGuard
) -> PickResultRead:
    shipment = shipment_service.get_shipment_or_404(session, shipment_id)
    record = shipment_service.pick_manual(
        session,
        shipment,
        shipment_item_id=payload.shipment_item_id,
        quantity=payload.quantity,
        operator_id=user.id,
    )
    session.refresh(shipment)
    item = next((row for row in shipment.items if row.id == record.shipment_item_id), None)
    return PickResultRead(
        accepted=True,
        result=PickResult.OK,
        message=record.message,
        shipment_id=shipment.id,
        shipment_item_id=record.shipment_item_id,
        sku_id=record.sku_id,
        sku_code=record.sku.sku_code if record.sku else "",
        picked_qty=item.picked_qty if item else 0,
        quantity=item.quantity if item else 0,
        shipment_status=shipment.status,
        progress=shipment.progress,
    )


@router.post("/{shipment_id}/pack", response_model=ShipmentRead, summary="复核打包")
def pack(
    shipment_id: int, payload: PackRequest, session: DbSession, user: WarehouseGuard
) -> ShipmentRead:
    shipment = shipment_service.get_shipment_or_404(session, shipment_id)
    shipment = shipment_service.pack(
        session,
        shipment,
        package_count=payload.package_count,
        weight_g=payload.weight_g,
        remark=payload.remark,
        operator_id=user.id,
    )
    return shipment_service.to_shipment_read(session, shipment)


@router.post(
    "/{shipment_id}/ship", response_model=ShipmentActionResult, summary="出库发货（扣减实际库存）"
)
def ship(
    shipment_id: int, payload: ShipRequest, session: DbSession, user: WarehouseGuard
) -> ShipmentActionResult:
    shipment = shipment_service.get_shipment_or_404(session, shipment_id)
    outbound = shipment_service.ship(
        session,
        shipment,
        carrier=payload.carrier,
        tracking_no=payload.tracking_no,
        remark=payload.remark,
        operator_id=user.id,
    )
    session.refresh(shipment)
    lines: list[OutboundLine] = shipment_service.to_outbound_lines(session, outbound)
    return ShipmentActionResult(
        shipment=shipment_service.to_shipment_read(session, shipment),
        message=f"已出库 {len(lines)} 个 SKU，实际库存已扣减",
        outbound=lines,
    )


@router.post("/{shipment_id}/cancel", response_model=ShipmentRead, summary="取消发货单")
def cancel(
    shipment_id: int, payload: CancelShipmentRequest, session: DbSession, user: WarehouseGuard
) -> ShipmentRead:
    shipment = shipment_service.get_shipment_or_404(session, shipment_id)
    shipment = shipment_service.cancel(
        session, shipment, reason=payload.reason, operator_id=user.id
    )
    return shipment_service.to_shipment_read(session, shipment)
