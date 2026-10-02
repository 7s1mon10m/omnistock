"""Aggregate router for API version 1."""

from fastapi import APIRouter

from app.api.v1 import (
    alerts,
    auth,
    bundles,
    channel_adapters,
    channels,
    exports,
    audit_logs,
    inventory,
    notifications,
    orders,
    products,
    purchase,
    reports,
    return_orders,
    shipments,
    stocktakes,
    suppliers,
    transfers,
    users,
    warehouses,
)
from app.core.config import settings

api_router = APIRouter(prefix=settings.API_V1_PREFIX)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(warehouses.router)
# products declares /skus/resolve before /skus/{sku_id} internally, so the
# literal path is never captured by the parameterised one.
api_router.include_router(products.router)
api_router.include_router(bundles.router)
api_router.include_router(inventory.router)
api_router.include_router(channels.router)
# orders declares /orders/exceptions, /orders/sync-logs and the import routes
# before /orders/{order_id} for the same reason.
api_router.include_router(orders.router)
api_router.include_router(shipments.router)
api_router.include_router(suppliers.router)
api_router.include_router(purchase.router)
api_router.include_router(transfers.router)
# alerts declares /alerts/scan before /alerts/{alert_id}/... and
# notifications declares /settings/... first, for the same literal-path reason.
api_router.include_router(alerts.router)
api_router.include_router(notifications.router)
api_router.include_router(return_orders.router)
api_router.include_router(stocktakes.router)
api_router.include_router(reports.router)
# exports declares /{report}.csv; audit logs and adapters have no parameter
# routes to clash with.
api_router.include_router(exports.router)
api_router.include_router(audit_logs.router)
api_router.include_router(channel_adapters.router)
