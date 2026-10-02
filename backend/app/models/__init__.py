"""ORM models.

Importing this package registers every table on ``Base.metadata``, which is what
Alembic and ``init_db`` rely on.
"""

from app.models.base import SoftDeleteMixin, TimestampMixin, enum_type, utcnow
from app.models.channel import Channel, ChannelPlatform, ChannelProduct, ChannelShop
from app.models.inventory import (
    InventoryStock,
    InventoryTransaction,
    InventoryTransactionType,
)
from app.models.order import (
    ExceptionStatus,
    ExceptionType,
    ImportBatch,
    OrderException,
    OrderSource,
    OrderStatus,
    OrderSyncLog,
    SalesOrder,
    SalesOrderItem,
    SyncResult,
)
from app.models.product import (
    BundleComponent,
    Sku,
    SkuBarcode,
    SkuStatus,
    Spu,
    SpuStatus,
    SpuType,
)
from app.models.role import Permission, Role, role_permissions, user_roles
from app.models.shipment import (
    PickRecord,
    PickResult,
    Shipment,
    ShipmentItem,
    ShipmentItemStatus,
    ShipmentStatus,
)
from app.models.purchase import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    PurchaseReceipt,
    PurchaseReceiptItem,
    ReceiptStatus,
)
from app.models.supplier import Supplier
from app.models.transfer import StockTransfer, StockTransferItem, TransferStatus
from app.models.user import RefreshToken, User, UserStatus
from app.models.warehouse import Warehouse, WarehouseLocation, WarehouseType

__all__ = [
    "BundleComponent",
    "Channel",
    "ChannelPlatform",
    "ChannelProduct",
    "ChannelShop",
    "ExceptionStatus",
    "ExceptionType",
    "ImportBatch",
    "InventoryStock",
    "InventoryTransaction",
    "InventoryTransactionType",
    "OrderException",
    "OrderSource",
    "OrderStatus",
    "OrderSyncLog",
    "Permission",
    "PickRecord",
    "PickResult",
    "PurchaseOrder",
    "PurchaseOrderItem",
    "PurchaseOrderStatus",
    "PurchaseReceipt",
    "PurchaseReceiptItem",
    "ReceiptStatus",
    "RefreshToken",
    "Role",
    "SalesOrder",
    "SalesOrderItem",
    "Shipment",
    "ShipmentItem",
    "ShipmentItemStatus",
    "ShipmentStatus",
    "Sku",
    "SkuBarcode",
    "SkuStatus",
    "SoftDeleteMixin",
    "Spu",
    "SpuStatus",
    "SpuType",
    "StockTransfer",
    "StockTransferItem",
"StockTransferItem",
    "Supplier",
    "SyncResult",
    "TimestampMixin",
    "TransferStatus",
"User",
    "UserStatus",
    "Warehouse",
    "WarehouseLocation",
    "WarehouseType",
    "enum_type",
    "role_permissions",
    "user_roles",
    "utcnow",
]
