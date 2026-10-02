"""Alert rules, alerts and replenishment suggestions."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.v1.guards import AdminGuard, BuyerGuard, ViewerGuard
from app.core.deps import DbSession
from app.models.alert import AlertRuleScope, AlertStatus, AlertType, SuggestionStatus
from app.repositories import alert_repo
from app.schemas.alert import (
    AckAlertRequest,
    AlertRead,
    AlertRuleIn,
    AlertRuleRead,
    AlertRuleUpdate,
    ScanResult,
    SuggestionRead,
    SuggestionToPurchaseOrder,
)
from app.schemas.common import Page
from app.services import alert_service, replenish_service

router = APIRouter(tags=["alerts"])


# ------------------------------------------------------------------- rules
@router.get("/alert-rules", response_model=list[AlertRuleRead], summary="预警规则列表")
def list_alert_rules(
    session: DbSession,
    _: ViewerGuard,
    scope: AlertRuleScope | None = None,
    enabled: bool | None = None,
) -> list[AlertRuleRead]:
    rules = alert_repo.list_rules(session, scope=scope, enabled=enabled)
    return [alert_service.to_rule_read(rule) for rule in rules]


@router.post(
    "/alert-rules", response_model=AlertRuleRead, status_code=201, summary="创建预警规则"
)
def create_alert_rule(
    payload: AlertRuleIn, session: DbSession, _: AdminGuard
) -> AlertRuleRead:
    return alert_service.to_rule_read(alert_service.create_rule(session, payload))


@router.put("/alert-rules/{rule_id}", response_model=AlertRuleRead, summary="更新预警规则")
def update_alert_rule(
    rule_id: int, payload: AlertRuleUpdate, session: DbSession, _: AdminGuard
) -> AlertRuleRead:
    rule = alert_service.update_rule(session, rule_id, payload)
    return alert_service.to_rule_read(rule)


@router.delete("/alert-rules/{rule_id}", status_code=204, summary="删除预警规则")
def delete_alert_rule(rule_id: int, session: DbSession, _: AdminGuard) -> None:
    alert_service.delete_rule(session, rule_id)


# ------------------------------------------------------------------ alerts
@router.get("/alerts", response_model=Page[AlertRead], summary="预警列表")
def list_alerts(
    session: DbSession,
    _: ViewerGuard,
    status: AlertStatus | None = None,
    type: AlertType | None = None,  # noqa: A002 - matches the enum name
    warehouse_id: int | None = None,
    sku_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Page[AlertRead]:
    result = alert_repo.list_alerts(
        session,
        status=status,
        type_=type,
        warehouse_id=warehouse_id,
        sku_id=sku_id,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[alert_service.to_read(alert) for alert in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post("/alerts/scan", response_model=ScanResult, summary="手动触发一次扫描")
def scan_alerts(session: DbSession, _: AdminGuard, warehouse_id: int | None = None) -> ScanResult:
    return alert_service.scan(session, warehouse_id=warehouse_id)


@router.post("/alerts/{alert_id}/ack", response_model=AlertRead, summary="确认预警")
def ack_alert(
    alert_id: int, payload: AckAlertRequest, session: DbSession, user: ViewerGuard
) -> AlertRead:
    alert = alert_service.acknowledge(
        session, alert_id, payload, operator_id=user.id
    )
    return alert_service.to_read(alert)


@router.post("/alerts/{alert_id}/resolve", response_model=AlertRead, summary="关闭预警")
def resolve_alert(alert_id: int, session: DbSession, _: AdminGuard) -> AlertRead:
    return alert_service.to_read(alert_service.resolve(session, alert_id))


# ------------------------------------------------------------- suggestions
@router.get(
    "/replenishment-suggestions",
    response_model=Page[SuggestionRead],
    summary="补货建议列表",
)
def list_suggestions(
    session: DbSession,
    _: ViewerGuard,
    status: SuggestionStatus | None = None,
    warehouse_id: int | None = None,
    sku_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Page[SuggestionRead]:
    result = alert_repo.list_suggestions(
        session,
        status=status,
        warehouse_id=warehouse_id,
        sku_id=sku_id,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[replenish_service.to_read(row) for row in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post(
    "/replenishment-suggestions/generate",
    response_model=list[SuggestionRead],
    summary="生成补货建议",
)
def generate_suggestions(
    session: DbSession,
    _: BuyerGuard,
    warehouse_id: int | None = None,
    sku_id: int | None = None,
) -> list[SuggestionRead]:
    created = replenish_service.generate(
        session, warehouse_id=warehouse_id, sku_id=sku_id
    )
    return [replenish_service.to_read(row) for row in created]


@router.post(
    "/replenishment-suggestions/{suggestion_id}/dismiss",
    response_model=SuggestionRead,
    summary="忽略补货建议",
)
def dismiss_suggestion(
    suggestion_id: int, session: DbSession, _: BuyerGuard
) -> SuggestionRead:
    suggestion = replenish_service.dismiss(session, suggestion_id)
    return replenish_service.to_read(suggestion)


@router.post(
    "/replenishment-suggestions/{suggestion_id}/to-purchase-order",
    summary="一键转采购单",
)
def to_purchase_order(
    suggestion_id: int,
    payload: SuggestionToPurchaseOrder,
    session: DbSession,
    user: BuyerGuard,
) -> dict:
    from app.services import purchase_service

    order, suggestion = replenish_service.to_purchase_order(
        session, suggestion_id, payload, operator_id=user.id
    )
    return {
        "purchase_order": purchase_service.to_order_read(session, order).model_dump(),
        "suggestion": replenish_service.to_read(suggestion).model_dump(),
    }
