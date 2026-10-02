"""Order endpoints: list, import, exception handling and the sync log.

Route order matters: every literal path (``/orders/exceptions``,
``/orders/sync-logs``, ``/orders/import`` …) is declared before
``/orders/{order_id}`` so the parameterised route never swallows them.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import Response

from app.adapters import adapter_for_filename
from app.adapters.base import ParsedImport
from app.adapters.csv_adapter import empty_template
from app.api.v1.guards import OperatorGuard, ViewerGuard
from app.core.deps import DbSession
from app.core.errors import IMPORT_EMPTY, BusinessError
from app.models.order import ExceptionStatus, ExceptionType, OrderStatus, SyncResult
from app.repositories import order_repo
from app.schemas.common import Page
from app.schemas.order import (
    CancelOrderRequest,
    ImportBatchRead,
    ImportResultRead,
    MarkPaidRequest,
    OrderActionResult,
    OrderExceptionRead,
    OrderImportRequest,
    OrderListRead,
    OrderRead,
    SyncLogRead,
)
from app.services import order_import_service, order_service

router = APIRouter(prefix="/orders", tags=["orders"])


# ------------------------------------------------------------------- listing
@router.get("", response_model=Page[OrderListRead], summary="订单列表")
def list_orders(
    session: DbSession,
    _: ViewerGuard,
    channel_id: int | None = None,
    status: OrderStatus | None = None,
    keyword: str | None = None,
    only_exception: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Page[OrderListRead]:
    result = order_repo.list_orders(
        session,
        channel_id=channel_id,
        status=status,
        keyword=keyword,
        only_exception=only_exception,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[order_service.to_list_read(order) for order in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.get(
    "/exceptions", response_model=Page[OrderExceptionRead], summary="异常订单列表"
)
def list_exceptions(
    session: DbSession,
    _: ViewerGuard,
    status: ExceptionStatus | None = ExceptionStatus.OPEN,
    type: ExceptionType | None = None,
    order_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Page[OrderExceptionRead]:
    result = order_repo.list_exceptions(
        session, status=status, type_=type, order_id=order_id, page=page, page_size=page_size
    )
    return Page(
        items=[order_service.to_exception_read(exc) for exc in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.get("/sync-logs", response_model=Page[SyncLogRead], summary="订单同步日志")
def list_sync_logs(
    session: DbSession,
    _: ViewerGuard,
    channel_id: int | None = None,
    channel_order_no: str | None = None,
    result_: SyncResult | None = Query(default=None, alias="result"),
    batch_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Page[SyncLogRead]:
    result = order_repo.list_sync_logs(
        session,
        channel_id=channel_id,
        channel_order_no=channel_order_no,
        result=result_,
        batch_id=batch_id,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[order_service.to_sync_log_read(log) for log in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.get(
    "/import-batches", response_model=Page[ImportBatchRead], summary="导入批次记录"
)
def list_import_batches(
    session: DbSession,
    _: ViewerGuard,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Page[ImportBatchRead]:
    result = order_repo.list_import_batches(session, page=page, page_size=page_size)
    return Page(
        items=[ImportBatchRead.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.get("/import-template.csv", summary="下载订单导入 CSV 模板")
def download_template() -> Response:
    return Response(
        content=empty_template(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="order-import-template.csv"'},
    )


# -------------------------------------------------------------------- import
@router.post("/import", response_model=ImportResultRead, summary="上传 CSV / JSON 导入订单")
async def import_orders(
    session: DbSession,
    user: OperatorGuard,
    file: Annotated[UploadFile, File(description="CSV 或 JSON 订单导出文件")],
) -> ImportResultRead:
    filename = file.filename or ""
    adapter = adapter_for_filename(filename)
    content = await file.read()
    if not content:
        raise BusinessError(IMPORT_EMPTY, "上传的文件是空的", http_status=400)

    parsed = adapter.parse(content, filename)
    return order_import_service.import_orders(
        session,
        parsed,
        source=adapter.source,
        filename=filename,
        operator_id=user.id,
    )


@router.post("/import-json", response_model=ImportResultRead, summary="以 JSON 请求体导入订单")
def import_orders_json(
    payload: OrderImportRequest, session: DbSession, user: OperatorGuard
) -> ImportResultRead:
    parsed = ParsedImport(orders=list(payload.orders), row_errors=[])
    return order_import_service.import_orders(
        session,
        parsed,
        source=payload.source,
        filename=payload.filename,
        operator_id=user.id,
    )


# ------------------------------------------------------------------- detail
@router.get("/{order_id}", response_model=OrderRead, summary="订单详情")
def get_order(order_id: int, session: DbSession, _: ViewerGuard) -> OrderRead:
    order = order_service.get_order_or_404(session, order_id)
    return order_service.to_order_read(session, order)


@router.post("/{order_id}/mark-paid", response_model=OrderActionResult, summary="标记付款并占用库存")
def mark_paid(
    order_id: int, payload: MarkPaidRequest, session: DbSession, user: OperatorGuard
) -> OrderActionResult:
    order = order_service.get_order_or_404(session, order_id)
    result = order_service.mark_paid(
        session, order, paid_at=payload.paid_at, operator_id=user.id
    )
    session.refresh(order)
    return OrderActionResult(
        order=order_service.to_order_read(session, order),
        reserved=order_service.to_lines(session, result.lines),
        exceptions=[order_service.to_exception_read(e) for e in result.exceptions],
        message="已占用库存" if result.ok else "库存不足，已转入异常订单",
    )


@router.post("/{order_id}/cancel", response_model=OrderActionResult, summary="取消订单并释放库存")
def cancel_order(
    order_id: int, payload: CancelOrderRequest, session: DbSession, user: OperatorGuard
) -> OrderActionResult:
    order = order_service.get_order_or_404(session, order_id)
    released = order_service.cancel_order(
        session, order, reason=payload.reason, operator_id=user.id
    )
    session.refresh(order)
    return OrderActionResult(
        order=order_service.to_order_read(session, order),
        released=order_service.to_lines(session, released),
        message=f"已释放 {len(released)} 个 SKU 的占用",
    )


@router.post(
    "/{order_id}/retry-reserve", response_model=OrderActionResult, summary="重新尝试占用库存"
)
def retry_reserve(order_id: int, session: DbSession, user: OperatorGuard) -> OrderActionResult:
    order = order_service.get_order_or_404(session, order_id)
    result = order_service.retry_reserve(session, order, operator_id=user.id)
    session.refresh(order)
    return OrderActionResult(
        order=order_service.to_order_read(session, order),
        reserved=order_service.to_lines(session, result.lines),
        exceptions=[order_service.to_exception_read(e) for e in result.exceptions],
        message="已补齐占用" if result.ok else "仍有 SKU 缺货",
    )
