"""Alert and replenishment data access."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.alert import (
    Alert,
    AlertRule,
    AlertRuleScope,
    AlertStatus,
    AlertType,
    ReplenishmentSuggestion,
    SuggestionStatus,
)
from app.utils.pagination import PageResult, paginate


# ------------------------------------------------------------------- rules
def get_rule(session: Session, rule_id: int) -> AlertRule | None:
    return session.get(AlertRule, rule_id)


def list_rules(
    session: Session, *, scope: AlertRuleScope | None = None, enabled: bool | None = None
) -> list[AlertRule]:
    stmt = select(AlertRule)
    if scope:
        stmt = stmt.where(AlertRule.scope == scope)
    if enabled is not None:
        stmt = stmt.where(AlertRule.enabled == bool(enabled))
    stmt = stmt.order_by(AlertRule.id)
    return list(session.scalars(stmt))


def find_rule_by_target(
    session: Session, scope: AlertRuleScope, *, spu_id: int | None, sku_id: int | None, warehouse_id: int | None
) -> AlertRule | None:
    """同一范围只允许一条规则（scope + 三个目标列全等）。"""
    stmt = select(AlertRule).where(
        AlertRule.scope == scope,
        AlertRule.spu_id == spu_id,
        AlertRule.sku_id == sku_id,
        AlertRule.warehouse_id == warehouse_id,
    )
    return session.scalar(stmt)


def create_rule(session: Session, **fields) -> AlertRule:
    rule = AlertRule(**fields)
    session.add(rule)
    session.flush()
    return rule


# ------------------------------------------------------------------ alerts
def get_alert(session: Session, alert_id: int) -> Alert | None:
    return session.get(Alert, alert_id)


def get_alert_by_dedup(session: Session, dedup_key: str) -> Alert | None:
    """占用 dedup_key 的未解决告警（open / acked 都算未解决）。"""
    stmt = select(Alert).where(
        Alert.dedup_key == dedup_key,
        Alert.status.in_([AlertStatus.OPEN, AlertStatus.ACKED]),
    )
    return session.scalar(stmt)


def list_alerts(
    session: Session,
    *,
    status: AlertStatus | None = None,
    type_: AlertType | None = None,
    warehouse_id: int | None = None,
    sku_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    stmt = select(Alert)
    if status:
        stmt = stmt.where(Alert.status == status)
    if type_:
        stmt = stmt.where(Alert.type == type_)
    if warehouse_id:
        stmt = stmt.where(Alert.warehouse_id == warehouse_id)
    if sku_id:
        stmt = stmt.where(Alert.sku_id == sku_id)
    stmt = stmt.order_by(Alert.id.desc())
    return paginate(session, stmt, page, page_size)


def count_open_alerts(session: Session) -> int:
    stmt = select(func.count()).select_from(Alert).where(Alert.status == AlertStatus.OPEN)
    return session.scalar(stmt) or 0


def create_alert(session: Session, **fields) -> Alert:
    alert = Alert(**fields)
    session.add(alert)
    session.flush()
    return alert


# -------------------------------------------------------------- suggestions
def get_suggestion(session: Session, suggestion_id: int) -> ReplenishmentSuggestion | None:
    return session.get(ReplenishmentSuggestion, suggestion_id)


def get_suggestion_by_dedup(session: Session, dedup_key: str) -> ReplenishmentSuggestion | None:
    stmt = select(ReplenishmentSuggestion).where(
        ReplenishmentSuggestion.dedup_key == dedup_key,
        ReplenishmentSuggestion.status == SuggestionStatus.OPEN,
    )
    return session.scalar(stmt)


def list_suggestions(
    session: Session,
    *,
    status: SuggestionStatus | None = None,
    warehouse_id: int | None = None,
    sku_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    stmt = select(ReplenishmentSuggestion)
    if status:
        stmt = stmt.where(ReplenishmentSuggestion.status == status)
    if warehouse_id:
        stmt = stmt.where(ReplenishmentSuggestion.warehouse_id == warehouse_id)
    if sku_id:
        stmt = stmt.where(ReplenishmentSuggestion.sku_id == sku_id)
    stmt = stmt.order_by(ReplenishmentSuggestion.id.desc())
    return paginate(session, stmt, page, page_size)


def create_suggestion(session: Session, **fields) -> ReplenishmentSuggestion:
    suggestion = ReplenishmentSuggestion(**fields)
    session.add(suggestion)
    session.flush()
    return suggestion


def next_alert_no(session: Session, alert_id: int) -> str:
    from app.core.config import settings

    return f"{settings.ALERT_CODE_PREFIX}{alert_id:08d}"


def utc_cutoff(days: int) -> dt.datetime:
    from app.models.base import utcnow

    return utcnow() - dt.timedelta(days=days)
