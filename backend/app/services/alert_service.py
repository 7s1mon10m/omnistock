"""Low-stock alerting.

The scan is a single pass over ``inventory_stocks``.  Two rules keep it honest:

**Deduplication is per (SKU, warehouse, type), not per scan.**  A cron that runs
every hour against a SKU that stays below its safety stock must not produce 24
alerts a day.  The ``dedup_key`` column carries that state: an unresolved alert
holds the key, and only resolving it releases the key for the next occurrence.

**In-transit counts toward the threshold.**  Stock already on its way will
arrive; warning about it as if it did not exist is the classic false alarm that
teaches people to ignore alerts.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import (
    ALERT_NOT_FOUND,
    ALERT_RULE_DUPLICATE,
    ALERT_RULE_NOT_FOUND,
    BusinessError,
)
from app.domain import replenish_formula
from app.models.alert import (
    Alert,
    AlertRule,
    AlertRuleScope,
    AlertStatus,
    AlertType,
)
from app.models.base import utcnow
from app.models.inventory import InventoryStock
from app.models.notification import NotificationChannel, NotificationLevel
from app.repositories import alert_repo, product_repo
from app.schemas.alert import (
    AckAlertRequest,
    AlertRead,
    AlertRuleIn,
    AlertRuleRead,
    AlertRuleUpdate,
    ScanResult,
)
from app.services import notification_service


# --------------------------------------------------------------------- rules
def _validate_target(payload: AlertRuleIn) -> None:
    """A scope must carry exactly the columns it needs — no more, no less."""
    supplied = {
        AlertRuleScope.SKU: payload.sku_id,
        AlertRuleScope.CATEGORY: payload.spu_id,
        AlertRuleScope.WAREHOUSE: payload.warehouse_id,
    }
    if payload.scope in supplied and not supplied[payload.scope]:
        raise BusinessError(
            ALERT_RULE_NOT_FOUND,
            f"{payload.scope.value} 范围必须指定对应的目标",
            http_status=400,
        )
    for scope, value in supplied.items():
        if scope is not payload.scope and value:
            raise BusinessError(
                ALERT_RULE_NOT_FOUND,
                f"{scope.value} 只能用于 {scope.value} 范围的规则",
                http_status=400,
            )


def create_rule(session: Session, payload: AlertRuleIn) -> AlertRule:
    _validate_target(payload)
    existing = alert_repo.find_rule_by_target(
        session, payload.scope, spu_id=payload.spu_id, sku_id=payload.sku_id,
        warehouse_id=payload.warehouse_id,
    )
    if existing is not None:
        raise BusinessError(
            ALERT_RULE_DUPLICATE,
            f"该范围已存在规则「{existing.name}」",
            detail={"rule_id": existing.id},
            http_status=409,
        )
    if payload.sku_id and product_repo.get_sku(session, payload.sku_id) is None:
        raise BusinessError(ALERT_RULE_NOT_FOUND, "SKU 不存在", http_status=404)

    rule = alert_repo.create_rule(
        session,
        name=payload.name,
        scope=payload.scope,
        spu_id=payload.spu_id,
        sku_id=payload.sku_id,
        warehouse_id=payload.warehouse_id,
        threshold_qty=payload.threshold_qty,
        enabled=payload.enabled,
        notify_channels=payload.notify_channels,
        remark=payload.remark,
    )
    session.commit()
    return rule


def update_rule(session: Session, rule_id: int, payload: AlertRuleUpdate) -> AlertRule:
    rule = alert_repo.get_rule(session, rule_id)
    if rule is None:
        raise BusinessError(ALERT_RULE_NOT_FOUND, http_status=404)
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(rule, key, value)
    session.commit()
    return rule


def delete_rule(session: Session, rule_id: int) -> None:
    """Remove a rule.  Alerts already raised keep their own history."""
    rule = alert_repo.get_rule(session, rule_id)
    if rule is None:
        raise BusinessError(ALERT_RULE_NOT_FOUND, http_status=404)
    session.delete(rule)
    session.commit()


def to_rule_read(rule: AlertRule) -> AlertRuleRead:
    return AlertRuleRead(
        id=rule.id,
        name=rule.name,
        scope=rule.scope,
        spu_id=rule.spu_id,
        spu_name=rule.spu.name if rule.spu else "",
        sku_id=rule.sku_id,
        sku_code=rule.sku.sku_code if rule.sku else "",
        warehouse_id=rule.warehouse_id,
        warehouse_name=rule.warehouse.name if rule.warehouse else "",
        threshold_qty=rule.threshold_qty,
        enabled=rule.enabled,
        notify_channels=rule.notify_channels,
        remark=rule.remark,
        created_at=rule.created_at,
    )


# --------------------------------------------------------------------- scan
def _matching_rules(
    session: Session, stock: InventoryStock, all_rules: list[AlertRule]
) -> list[AlertRule]:
    """Which enabled rules apply to this (SKU, warehouse) row.

    Narrower scopes win, so a per-SKU rule overrides a per-warehouse one
    without the caller having to disable the broader rule.
    """
    spu_id = stock.sku.spu_id if stock.sku else None
    applicable = [
        rule
        for rule in all_rules
        if (
            (rule.scope == AlertRuleScope.SKU and rule.sku_id == stock.sku_id)
            or (rule.scope == AlertRuleScope.CATEGORY and rule.spu_id == spu_id)
            or (rule.scope == AlertRuleScope.WAREHOUSE and rule.warehouse_id == stock.warehouse_id)
            or rule.scope == AlertRuleScope.GLOBAL
        )
    ]
    order = {
        AlertRuleScope.SKU: 0,
        AlertRuleScope.CATEGORY: 1,
        AlertRuleScope.WAREHOUSE: 2,
        AlertRuleScope.GLOBAL: 3,
    }
    applicable.sort(key=lambda rule: order[rule.scope])
    return applicable


def _effective_safety(stock: InventoryStock, rules: list[AlertRule]) -> tuple[int, AlertRule | None]:
    """Threshold for this row: the narrowest rule's value, else the SKU's own."""
    for rule in rules:
        if rule.threshold_qty is not None:
            return rule.threshold_qty, rule
    return stock.safety_qty, (rules[0] if rules else None)


def scan(session: Session, *, warehouse_id: int | None = None) -> ScanResult:
    """Scan every stock row and open alerts for whatever is below safety.

    Also **resolves** alerts whose subject has recovered — a warning that stays
    red after the problem is fixed trains people to ignore the board.
    """
    from sqlalchemy import select

    result = ScanResult()

    stmt = select(InventoryStock)
    if warehouse_id is not None:
        stmt = stmt.where(InventoryStock.warehouse_id == warehouse_id)
    rows = list(session.scalars(stmt))
    result.scanned = len(rows)

    now = utcnow()
    # 规则只查一次：逐行再查一次在 SKU 多了以后是明显的 N+1。
    all_rules = alert_repo.list_rules(session, enabled=True)

    for stock in rows:
        rules = _matching_rules(session, stock, all_rules)
        safety, rule = _effective_safety(stock, rules)
        if safety <= 0:
            # 没人给它定安全库存，就不该被判定为「低库存」。
            continue

        available = stock.available_qty
        in_transit = stock.in_transit_qty
        covered = available + in_transit
        dedup = f"{stock.sku_id}:{stock.warehouse_id}"

        if replenish_formula.is_low_stock(
            available_qty=available, in_transit_qty=in_transit, safety_qty=safety
        ):
            if alert_repo.get_alert_by_dedup(session, dedup) is not None:
                result.alerts_skipped += 1
                continue

            gap = replenish_formula.shortfall(
                available_qty=available, in_transit_qty=in_transit, safety_qty=safety
            )
            alert_type = (
                AlertType.OUT_OF_STOCK if covered <= 0 else AlertType.LOW_STOCK
            )
            sku_label = stock.sku.display_name if stock.sku else str(stock.sku_id)
            wh_label = stock.warehouse.name if stock.warehouse else str(stock.warehouse_id)
            alert = alert_repo.create_alert(
                session,
                alert_no="",
                type=alert_type,
                status=AlertStatus.OPEN,
                rule_id=rule.id if rule else None,
                sku_id=stock.sku_id,
                warehouse_id=stock.warehouse_id,
                available_qty=available,
                in_transit_qty=in_transit,
                safety_qty=safety,
                gap_qty=gap,
                message=(
                    f"{sku_label} 在 {wh_label} 可售 {available}、在途 {in_transit}，"
                    f"低于安全库存 {safety}，缺口 {gap}"
                ),
                detected_at=now,
                dedup_key=dedup,
            )
            alert.alert_no = alert_repo.next_alert_no(session, alert.id)
            result.alerts_created += 1

            sent = _notify_new_alert(session, alert, rules)
            result.notifications_sent += sent
        else:
            # 恢复了：把同 key 的未解决告警结掉，释放 dedup_key。
            resolved = _resolve_recovered(session, dedup, now)
            result.resolved += resolved

    session.commit()
    return result


def _resolve_recovered(session: Session, dedup: str, now: dt.datetime) -> int:
    from sqlalchemy import select

    stmt = select(Alert).where(
        Alert.dedup_key == dedup,
        Alert.status.in_([AlertStatus.OPEN, AlertStatus.ACKED]),
    )
    count = 0
    for alert in session.scalars(stmt):
        alert.status = AlertStatus.RESOLVED
        alert.resolved_at = now
        # 清空唯一键，下一次低于阈值才能重新告警。
        alert.dedup_key = None
        count += 1
    return count


def _notify_new_alert(session: Session, alert: Alert, rules: list[AlertRule]) -> int:
    """Fan the alert out to the channels the matching rules ask for."""
    wanted: list[NotificationChannel] = []
    for rule in rules:
        for raw in rule.notify_channels.split(","):
            token = raw.strip()
            if not token:
                continue
            try:
                channel = NotificationChannel(token)
            except ValueError:
                continue
            if channel not in wanted:
                wanted.append(channel)
    if not wanted:
        wanted = notification_service.default_channels(session)

    level = (
        NotificationLevel.ERROR
        if alert.type == AlertType.OUT_OF_STOCK
        else NotificationLevel.WARNING
    )
    notification_service.notify(
        session,
        title=f"库存预警 · {alert.alert_no}",
        body=alert.message,
        level=level,
        category="alert",
        ref_type="alert",
        ref_id=alert.id,
        # 同一张告警只提醒一次，哪怕投递重试了好几次。
        dedup_key=f"alert:{alert.id}",
        channels=wanted,
    )
    return 1


# ---------------------------------------------------------------------- ack
def acknowledge(
    session: Session, alert_id: int, payload: AckAlertRequest, *, operator_id: int | None = None
) -> Alert:
    alert = alert_repo.get_alert(session, alert_id)
    if alert is None:
        raise BusinessError(ALERT_NOT_FOUND, http_status=404)
    if alert.status == AlertStatus.RESOLVED:
        raise BusinessError(
            ALERT_NOT_FOUND, "该预警已解决，无需确认", http_status=409
        )
    if alert.status == AlertStatus.OPEN:
        alert.status = AlertStatus.ACKED
        alert.acknowledged_by = operator_id
        alert.acknowledged_at = utcnow()
        if payload.remark:
            alert.message = f"{alert.message} | {payload.remark}"[:255]
        session.commit()
    return alert


def resolve(session: Session, alert_id: int, *, remark: str = "") -> Alert:
    """Manual close — the one way to silence an alert without restocking."""
    alert = alert_repo.get_alert(session, alert_id)
    if alert is None:
        raise BusinessError(ALERT_NOT_FOUND, http_status=404)
    alert.status = AlertStatus.RESOLVED
    alert.resolved_at = utcnow()
    alert.dedup_key = None
    if remark:
        alert.message = f"{alert.message} | {remark}"[:255]
    session.commit()
    return alert


def to_read(alert: Alert) -> AlertRead:
    operator = alert.acknowledged_by_user
    return AlertRead(
        id=alert.id,
        alert_no=alert.alert_no,
        type=alert.type,
        status=alert.status,
        rule_id=alert.rule_id,
        sku_id=alert.sku_id,
        sku_code=alert.sku.sku_code if alert.sku else "",
        sku_name=alert.sku.display_name if alert.sku else "",
        warehouse_id=alert.warehouse_id,
        warehouse_code=alert.warehouse.code if alert.warehouse else "",
        warehouse_name=alert.warehouse.name if alert.warehouse else "",
        available_qty=alert.available_qty,
        in_transit_qty=alert.in_transit_qty,
        safety_qty=alert.safety_qty,
        gap_qty=alert.gap_qty,
        message=alert.message,
        detected_at=alert.detected_at,
        acknowledged_by=alert.acknowledged_by,
        acknowledged_by_name=(operator.full_name or operator.username) if operator else "",
        acknowledged_at=alert.acknowledged_at,
        resolved_at=alert.resolved_at,
        created_at=alert.created_at,
    )


def prefix() -> str:
    return settings.ALERT_CODE_PREFIX
