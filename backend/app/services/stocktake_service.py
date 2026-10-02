"""盘点：录入实盘数 → 提交 → 审核 → 落账。

这一整套流程存在的唯一理由是：**盘盈盘亏会直接改库存**。

没有审核这一关，「输错一个数字」就等于「凭空多出 20 件货」，而库存是所有
下游决策（能不能卖、要不要补货）的基础。所以：

* 提交只是「我盘完了」，不改任何数字；
* 差异超过阈值时必须有人审核（40304）；
* 审核通过才写 ``stocktake_adjust`` 流水，并留下操作人、时间与原因。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import (
    STOCKTAKE_ALREADY_APPROVED,
    STOCKTAKE_APPROVAL_REQUIRED,
    STOCKTAKE_LINE_NOT_FOUND,
    STOCKTAKE_NOT_FOUND,
    STOCKTAKE_STATUS_INVALID,
    WAREHOUSE_NOT_FOUND,
    BusinessError,
)
from app.models.base import utcnow
from app.models.inventory import InventoryTransactionType
from app.models.stocktake import Stocktake, StocktakeItem, StocktakeStatus
from app.repositories import stocktake_repo, warehouse_repo
from app.schemas.stocktake import (
    StocktakeCountRequest,
    StocktakeCreate,
    StocktakeLineRead,
    StocktakeListRead,
    StocktakeRead,
)
from app.services import inventory_service

LEDGER_REF = "stocktake"


def get_or_404(session: Session, stocktake_id: int) -> Stocktake:
    stocktake = stocktake_repo.get(session, stocktake_id)
    if stocktake is None:
        raise BusinessError(STOCKTAKE_NOT_FOUND, http_status=404)
    return stocktake


def _item_or_404(stocktake: Stocktake, item_id: int) -> StocktakeItem:
    item = next((row for row in stocktake.items if row.id == item_id), None)
    if item is None:
        raise BusinessError(
            STOCKTAKE_LINE_NOT_FOUND, detail={"stocktake_item_id": item_id}, http_status=404
        )
    return item


def _user_name(session: Session, user_id: int | None) -> str:
    from app.repositories import user_repo

    if not user_id:
        return ""
    user = user_repo.get(session, user_id)
    return (user.full_name or user.username) if user else ""


# --------------------------------------------------------------------- create
def create(
    session: Session, payload: StocktakeCreate, *, operator_id: int | None = None
) -> Stocktake:
    if warehouse_repo.get(session, payload.warehouse_id) is None:
        raise BusinessError(WAREHOUSE_NOT_FOUND, http_status=404)

    stocktake = stocktake_repo.create(
        session,
        stocktake_no="",
        warehouse_id=payload.warehouse_id,
        status=StocktakeStatus.DRAFT,
        scope=payload.scope,
        created_by=operator_id,
        remark=payload.remark,
    )
    stocktake.stocktake_no = (
        f"{settings.STOCKTAKE_CODE_PREFIX}{stocktake.id:08d}"
    )

    # 账面快照：盘点期间如果又发生出入库，差异会显得不合理，但把账面冻结在
    # 建单这一刻至少让「差异」这个数字可复现、可解释。
    book = stocktake_repo.book_qty_map(session, payload.warehouse_id)
    if payload.sku_ids:
        book = {sku_id: qty for sku_id, qty in book.items() if sku_id in set(payload.sku_ids)}

    for line_no, (sku_id, qty) in enumerate(sorted(book.items()), start=1):
        stocktake_repo.create_item(
            session,
            stocktake_id=stocktake.id,
            line_no=line_no,
            sku_id=sku_id,
            book_qty=qty,
        )

    session.commit()
    session.refresh(stocktake)
    return stocktake


# --------------------------------------------------------------------- count
def count(
    session: Session,
    stocktake: Stocktake,
    payload: StocktakeCountRequest,
    *,
    operator_id: int | None = None,
) -> Stocktake:
    """录入实盘数。可以反复录，以最后一次为准。"""
    if stocktake.status != StocktakeStatus.DRAFT:
        raise BusinessError(
            STOCKTAKE_STATUS_INVALID,
            f"当前状态 {stocktake.status.value} 不能再录入",
            http_status=409,
        )

    for line in payload.items:
        item = _item_or_404(stocktake, line.stocktake_item_id)
        item.counted_qty = line.counted_qty
        item.counted_by = operator_id
        item.counted_at = utcnow()
        if line.reason:
            item.reason = line.reason

    session.commit()
    return stocktake


# -------------------------------------------------------------------- submit
def submit(session: Session, stocktake: Stocktake, *, operator_id: int | None = None) -> Stocktake:
    if stocktake.status != StocktakeStatus.DRAFT:
        raise BusinessError(
            STOCKTAKE_STATUS_INVALID,
            f"当前状态 {stocktake.status.value} 不能提交",
            http_status=409,
        )
    if stocktake.counted_lines == 0:
        raise BusinessError(STOCKTAKE_STATUS_INVALID, "还没录入任何实盘数", http_status=400)

    stocktake.status = StocktakeStatus.SUBMITTED
    stocktake.submitted_by = operator_id
    stocktake.submitted_at = utcnow()
    session.commit()
    return stocktake


# ------------------------------------------------------------------- approve
def approve(
    session: Session, stocktake: Stocktake, *, operator_id: int | None = None, remark: str = ""
) -> Stocktake:
    """审核通过 —— 这一刻才把差异写进库存。"""
    if stocktake.status == StocktakeStatus.APPROVED:
        raise BusinessError(STOCKTAKE_ALREADY_APPROVED, http_status=409)
    if stocktake.status != StocktakeStatus.SUBMITTED:
        raise BusinessError(
            STOCKTAKE_STATUS_INVALID,
            f"当前状态 {stocktake.status.value} 不能审核",
            http_status=409,
        )

    _apply_variance(session, stocktake, operator_id=operator_id)

    stocktake.status = StocktakeStatus.APPROVED
    stocktake.approved_by = operator_id
    stocktake.approved_at = utcnow()
    if remark:
        stocktake.remark = f"{stocktake.remark} | {remark}"[:255]
    session.commit()
    return stocktake


def _apply_variance(session: Session, stocktake: Stocktake, *, operator_id: int | None) -> None:
    """把每一行差异写成一条调整流水。"""
    for item in stocktake.items:
        variance = item.variance_qty
        if variance == 0 or item.adjusted:
            continue
        inventory_service._apply(  # noqa: SLF001 - 盘点调整直接复用库存内核
            session,
            sku_id=item.sku_id,
            warehouse_id=stocktake.warehouse_id,
            type_=InventoryTransactionType.STOCKTAKE_ADJUST,
            qty_delta=variance,
            ref_type=LEDGER_REF,
            ref_id=stocktake.id,
            operator_id=operator_id,
            remark=item.reason or f"盘点调整 {stocktake.stocktake_no}",
            idempotency_key=f"stocktake:{stocktake.id}:{item.id}",
        )
        item.adjusted = True


def cancel(session: Session, stocktake: Stocktake, *, reason: str = "") -> Stocktake:
    """只有没审核过的盘点单能取消 —— 一旦落账就只能通过新的调整来纠正。"""
    if stocktake.status == StocktakeStatus.APPROVED:
        raise BusinessError(
            STOCKTAKE_STATUS_INVALID, "已审核的盘点单不能取消", http_status=409
        )
    stocktake.status = StocktakeStatus.CANCELLED
    stocktake.cancelled_at = utcnow()
    if reason:
        stocktake.remark = f"{stocktake.remark} | 取消：{reason}"[:255]
    session.commit()
    return stocktake


def needs_approval(stocktake: Stocktake) -> bool:
    """差异是否大到必须有人过目。"""
    if not settings.STOCKTAKE_REQUIRE_APPROVAL:
        return False
    return stocktake.max_abs_variance > settings.STOCKTAKE_VARIANCE_THRESHOLD


def require_approval_if_needed(stocktake: Stocktake) -> None:
    if needs_approval(stocktake) and stocktake.status != StocktakeStatus.SUBMITTED:
        raise BusinessError(
            STOCKTAKE_APPROVAL_REQUIRED,
            f"最大差异 {stocktake.max_abs_variance} 件超过阈值 "
            f"{settings.STOCKTAKE_VARIANCE_THRESHOLD}，必须先提交并审核",
            detail={
                "max_abs_variance": stocktake.max_abs_variance,
                "threshold": settings.STOCKTAKE_VARIANCE_THRESHOLD,
            },
            http_status=403,
        )


# ----------------------------------------------------------------- read views
def to_line_read(session: Session, item: StocktakeItem) -> StocktakeLineRead:
    return StocktakeLineRead(
        id=item.id,
        line_no=item.line_no,
        sku_id=item.sku_id,
        sku_code=item.sku.sku_code if item.sku else "",
        sku_name=item.sku.display_name if item.sku else "",
        barcode=item.sku.barcode if item.sku else "",
        book_qty=item.book_qty,
        counted_qty=item.counted_qty,
        variance_qty=item.variance_qty,
        counted_by_name=_user_name(session, item.counted_by),
        counted_at=item.counted_at,
        reason=item.reason,
        adjusted=item.adjusted,
        remark=item.remark,
    )


def to_read(session: Session, stocktake: Stocktake) -> StocktakeRead:
    return StocktakeRead(
        id=stocktake.id,
        stocktake_no=stocktake.stocktake_no,
        warehouse_id=stocktake.warehouse_id,
        warehouse_code=stocktake.warehouse.code if stocktake.warehouse else "",
        warehouse_name=stocktake.warehouse.name if stocktake.warehouse else "",
        status=stocktake.status,
        scope=stocktake.scope,
        created_by=stocktake.created_by,
        created_by_name=_user_name(session, stocktake.created_by),
        submitted_by=stocktake.submitted_by,
        submitted_by_name=_user_name(session, stocktake.submitted_by),
        submitted_at=stocktake.submitted_at,
        approved_by=stocktake.approved_by,
        approved_by_name=_user_name(session, stocktake.approved_by),
        approved_at=stocktake.approved_at,
        remark=stocktake.remark,
        total_lines=len(stocktake.items),
        counted_lines=stocktake.counted_lines,
        variance_lines=stocktake.variance_lines,
        total_variance=stocktake.total_variance,
        max_abs_variance=stocktake.max_abs_variance,
        items=[
            to_line_read(session, item)
            for item in sorted(stocktake.items, key=lambda r: r.line_no)
        ],
        created_at=stocktake.created_at,
    )


def to_list_read(stocktake: Stocktake) -> StocktakeListRead:
    return StocktakeListRead(
        id=stocktake.id,
        stocktake_no=stocktake.stocktake_no,
        warehouse_name=stocktake.warehouse.name if stocktake.warehouse else "",
        status=stocktake.status,
        scope=stocktake.scope,
        total_lines=len(stocktake.items),
        counted_lines=stocktake.counted_lines,
        variance_lines=stocktake.variance_lines,
        total_variance=stocktake.total_variance,
        created_at=stocktake.created_at,
    )
