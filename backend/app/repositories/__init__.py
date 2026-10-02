"""Data access layer.

Repositories own the SQL; services own the rules.  Nothing above this layer
writes a query.
"""

from app.repositories import (
    alert_repo,
    channel_repo,
    inventory_repo,
    notification_repo,
    order_repo,
    product_repo,
    purchase_repo,
    report_repo,
    return_repo,
    shipment_repo,
    stocktake_repo,
    supplier_repo,
    transfer_repo,
    user_repo,
    warehouse_repo,
)

__all__ = [
    "alert_repo",
    "channel_repo",
    "inventory_repo",
    "notification_repo",
    "order_repo",
    "product_repo",
    "purchase_repo",
    "report_repo",
    "return_repo",
    "shipment_repo",
    "stocktake_repo",
    "supplier_repo",
    "transfer_repo",
    "user_repo",
    "warehouse_repo",
]
