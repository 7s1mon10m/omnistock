"""ORM models.

Importing this package registers every table on ``Base.metadata``, which is what
Alembic and ``init_db`` rely on.
"""

from app.models.base import SoftDeleteMixin, TimestampMixin, utcnow
from app.models.inventory import (
    InventoryStock,
    InventoryTransaction,
    InventoryTransactionType,
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
from app.models.user import RefreshToken, User, UserStatus
from app.models.warehouse import Warehouse, WarehouseLocation, WarehouseType

__all__ = [
    "BundleComponent",
    "InventoryStock",
    "InventoryTransaction",
    "InventoryTransactionType",
    "Permission",
    "RefreshToken",
    "Role",
    "Sku",
    "SkuBarcode",
    "SkuStatus",
    "SoftDeleteMixin",
    "Spu",
    "SpuStatus",
    "SpuType",
    "TimestampMixin",
    "User",
    "UserStatus",
    "Warehouse",
    "WarehouseLocation",
    "WarehouseType",
    "role_permissions",
    "user_roles",
    "utcnow",
]
