"""The order import pipeline.

One uploaded file becomes one :class:`ImportBatch`.  Every order row is processed
independently and committed on its own, so a single bad row never costs the
operator the rest of the file — the batch report tells them exactly what failed
and why.

Idempotency lives here: an order whose ``(channel, channel_order_no)`` already
exists is recorded as ``duplicate`` and **never** touches stock again.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.adapters.base import ParsedImport, row_error
from app.core.config import settings
from app.core.errors import (
    CHANNEL_NOT_FOUND,
    CHANNEL_SHOP_NOT_FOUND,
    IMPORT_EMPTY,
    IMPORT_ROW_LIMIT_EXCEEDED,
    WAREHOUSE_NOT_FOUND,
    BusinessError,
)
from app.models.base import utcnow
from app.models.order import OrderSource, OrderStatus, SyncResult
from app.repositories import channel_repo, order_repo, warehouse_repo
from app.schemas.order import ImportErrorRow, ImportResultRead
from app.services import channel_service, combo_service, order_service


def import_orders(
    session: Session,
    parsed: ParsedImport,
    *,
    source: OrderSource = OrderSource.IMPORT_JSON,
    filename: str = "",
    operator_id: int | None = None,
) -> ImportResultRead:
    orders = parsed.orders
    errors: list[ImportErrorRow] = list(parsed.row_errors)

    if not orders and not errors:
        raise BusinessError(IMPORT_EMPTY, "导入内容为空", http_status=400)
    if len(orders) > settings.IMPORT_MAX_ROWS:
        raise BusinessError(
            IMPORT_ROW_LIMIT_EXCEEDED,
            f"单次导入最多 {settings.IMPORT_MAX_ROWS} 个订单，本次 {len(orders)} 个",
            http_status=400,
        )

    batch = order_repo.create_import_batch(
        session,
        source=source,
        filename=filename,
        total_rows=len(orders),
        operator_id=operator_id,
    )
    session.commit()

    created = duplicates = reserved = exceptions = 0
    # Rows that failed to parse already count as failures for this batch.
    failed = len(parsed.row_errors)

    for index, payload in enumerate(orders, start=1):
        channel = channel_repo.get_channel_by_code(session, payload.channel_code)
        channel_id = channel.id if channel else None

        try:
            if channel is None:
                raise BusinessError(
                    CHANNEL_NOT_FOUND,
                    f"渠道 {payload.channel_code} 不存在",
                    http_status=404,
                )
            if not channel.is_active:
                raise BusinessError(
                    CHANNEL_NOT_FOUND, f"渠道 {payload.channel_code} 已停用", http_status=404
                )

            shop_id = None
            if payload.shop_code:
                shop = channel_repo.get_shop_by_code(session, channel.id, payload.shop_code)
                if shop is None:
                    raise BusinessError(
                        CHANNEL_SHOP_NOT_FOUND,
                        f"渠道 {payload.channel_code} 下没有店铺 {payload.shop_code}",
                        http_status=404,
                    )
                shop_id = shop.id

            warehouse_id = None
            if payload.warehouse_code:
                warehouse = warehouse_repo.get_by_code(session, payload.warehouse_code)
                if warehouse is None:
                    raise BusinessError(
                        WAREHOUSE_NOT_FOUND,
                        f"仓库 {payload.warehouse_code} 不存在",
                        http_status=404,
                    )
                warehouse_id = warehouse.id

            # ---------------------------------------------------- idempotency
            existing = order_repo.get_order_by_channel_no(
                session, channel.id, payload.channel_order_no
            )
            if existing is not None:
                duplicates += 1
                order_repo.create_sync_log(
                    session,
                    channel_id=channel.id,
                    shop_id=shop_id,
                    channel_order_no=payload.channel_order_no,
                    order_id=existing.id,
                    batch_id=batch.id,
                    result=SyncResult.DUPLICATE,
                    message=f"订单已存在（内部单号 {existing.order_no}），未重复占用库存",
                )
                session.commit()
                continue

            # ------------------------------------------------ map to SKUs
            resolved: list[tuple[str, int, int, int, bool]] = []
            has_bundle = False
            total_cents = 0
            for item in payload.items:
                sku_id = channel_service.resolve_sku_id(
                    session, channel.id, item.channel_product_code
                )
                # A bundle SKU holds no stock itself; flag it so the UI can show
                # that this line will be exploded at reservation time.
                is_bundle = bool(combo_service.component_pairs(session, sku_id))
                has_bundle = has_bundle or is_bundle
                total_cents += item.unit_price_cents * item.quantity
                resolved.append(
                    (item.channel_product_code, sku_id, item.quantity, item.unit_price_cents, is_bundle)
                )

            order = order_repo.create_order(
                session,
                channel_id=channel.id,
                shop_id=shop_id,
                channel_order_no=payload.channel_order_no,
                status=OrderStatus.PENDING_PAYMENT,
                warehouse_id=warehouse_id,
                buyer_nick=payload.buyer_nick,
                total_amount_cents=total_cents,
                is_bundle=has_bundle,
                source=source,
                remark=payload.remark,
            )
            for line_no, (code, sku_id, qty, price, is_bundle) in enumerate(resolved, start=1):
                order_repo.create_item(
                    session,
                    order_id=order.id,
                    line_no=line_no,
                    channel_product_code=code,
                    sku_id=sku_id,
                    quantity=qty,
                    unit_price_cents=price,
                    is_bundle=is_bundle,
                )
            order.order_no = order_repo.next_order_no(session, settings.ORDER_CODE_PREFIX, order.id)
            session.flush()

            # -------------------------------------------------- auto reserve
            paid_at = payload.paid_at
            if paid_at is None and settings.ORDER_IMPORT_ASSUME_PAID:
                paid_at = utcnow()
            if paid_at is not None:
                order.paid_at = paid_at
                order.status = OrderStatus.PENDING_FULFILLMENT
                session.flush()
                order_service.reserve_order(
                    session, order, operator_id=operator_id, commit=False
                )

            session.commit()

            created += 1
            if order.status == OrderStatus.RESERVED:
                reserved += 1
            elif order.status == OrderStatus.EXCEPTION:
                exceptions += 1

            order_repo.create_sync_log(
                session,
                channel_id=channel.id,
                shop_id=shop_id,
                channel_order_no=payload.channel_order_no,
                order_id=order.id,
                batch_id=batch.id,
                result=SyncResult.CREATED,
                message=f"已创建订单 {order.order_no}，状态 {order.status.value}",
            )
            session.commit()

        except BusinessError as exc:
            session.rollback()
            failed += 1
            errors.append(
                row_error(index, exc.code, exc.message, payload.channel_order_no)
            )
            if channel_id is not None:
                order_repo.create_sync_log(
                    session,
                    channel_id=channel_id,
                    shop_id=None,
                    channel_order_no=payload.channel_order_no,
                    batch_id=batch.id,
                    result=SyncResult.FAILED,
                    message=exc.message,
                )
                session.commit()
        except Exception as exc:  # pragma: no cover - unexpected, must not kill the batch
            session.rollback()
            failed += 1
            errors.append(
                row_error(index, 50000, f"未预期的错误：{exc}", payload.channel_order_no)
            )

    batch.total_rows = len(orders)
    batch.created_orders = created
    batch.duplicate_orders = duplicates
    batch.failed_rows = failed
    batch.reserved_orders = reserved
    batch.exception_orders = exceptions
    batch.errors = [error.model_dump() for error in errors]
    session.commit()

    return ImportResultRead(
        batch_id=batch.id,
        source=source,
        total_rows=len(orders),
        created_orders=created,
        duplicate_orders=duplicates,
        failed_rows=failed,
        reserved_orders=reserved,
        exception_orders=exceptions,
        errors=errors,
    )
