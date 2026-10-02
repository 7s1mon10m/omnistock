"""Role guards shared by the routers.

The four business personas map to concrete guards:

* ``admin`` / ``owner`` — warehouse layout, users and roles
* ``operator``          — product, SKU, barcode and bundle maintenance
* ``buyer``             — suppliers and purchase orders (M4)
* ``warehouse``         — receipts, picking, counting and stock adjustments
"""

from __future__ import annotations

from typing import Annotated

from app.core.deps import require_roles
from app.models.user import User

#: 店主 + 系统管理员
AdminGuard = Annotated[User, require_roles("admin", "owner")]
#: 商品维护
OperatorGuard = Annotated[User, require_roles("admin", "owner", "operator")]
#: 采购
BuyerGuard = Annotated[User, require_roles("admin", "owner", "buyer")]
#: 仓内作业与库存调整
WarehouseGuard = Annotated[User, require_roles("admin", "owner", "warehouse")]
#: 任何已登录用户
ViewerGuard = Annotated[User, require_roles("admin", "owner", "operator", "buyer", "warehouse")]
