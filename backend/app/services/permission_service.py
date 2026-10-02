"""Role and permission rules for the four business personas plus admin.

Permissions are seeded from :data:`ROLE_PERMISSIONS`.  Later milestones reuse
the same table (a supplier manager, a picker, a stocktake approver, ...) so the
list is deliberately wider than what M1 already enforces.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.role import Permission, Role
from app.models.user import User

#: The four business roles described in the project document.
BUSINESS_ROLES = ("owner", "operator", "buyer", "warehouse")

# role -> permission codes granted by default
ROLE_PERMISSIONS: dict[str, list[str]] = {
    "operator": [
        "spu:read",
        "spu:create",
        "spu:update",
        "sku:read",
        "sku:create",
        "sku:update",
        "sku:barcode",
        "bundle:read",
        "bundle:manage",
        "inventory:read",
        "channel:read",
        "channel:manage",
        "order:read",
        "order:manage",
        "shipment:read",
        "shipment:create",
        "notification:read",
    ],
    "buyer": [
        "spu:read",
        "sku:read",
        "inventory:read",
        "channel:read",
        "order:read",
        "shipment:read",
        "supplier:read",
        "supplier:manage",
        "purchase:read",
        "purchase:manage",
        "notification:read",
    ],
    "warehouse": [
        "spu:read",
        "sku:read",
        "inventory:read",
        "inventory:adjust",
        "order:read",
        "shipment:read",
        "shipment:pick",
        "shipment:ship",
        "receipt:read",
        "receipt:manage",
        "pick:read",
        "pick:manage",
        "stocktake:read",
        "stocktake:manage",
        "transfer:read",
        "transfer:manage",
        "notification:read",
    ],
    "owner": [
        "spu:read",
        "spu:create",
        "spu:update",
        "sku:read",
        "sku:create",
        "sku:update",
        "sku:barcode",
        "bundle:read",
        "bundle:manage",
        "inventory:read",
        "inventory:adjust",
        "warehouse:manage",
        "user:manage",
        "role:manage",
        "channel:read",
        "channel:manage",
        "order:read",
        "order:manage",
        "shipment:read",
        "shipment:pick",
        "shipment:ship",
        "report:read",
        "audit:read",
        "notification:read",
    ],
    "admin": [
        "spu:read",
        "spu:create",
        "spu:update",
        "sku:read",
        "sku:create",
        "sku:update",
        "sku:barcode",
        "bundle:read",
        "bundle:manage",
        "inventory:read",
        "inventory:adjust",
        "warehouse:manage",
        "user:manage",
        "role:manage",
        "channel:read",
        "channel:manage",
        "order:read",
        "order:manage",
        "supplier:read",
        "supplier:manage",
        "purchase:read",
        "purchase:manage",
        "receipt:read",
        "receipt:manage",
        "pick:read",
        "pick:manage",
        "stocktake:read",
        "stocktake:manage",
        "transfer:read",
        "transfer:manage",
        "report:read",
        "audit:read",
        "notification:read",
    ],
}

ROLE_DESCRIPTIONS = {
    "owner": "店主/管理员：查看经营情况、配置仓库与权限",
    "operator": "运营人员：管理商品、渠道与售后",
    "buyer": "采购人员：供应商、采购单与到货跟踪",
    "warehouse": "仓库人员：收货、拣货、发货、盘点与调拨",
    "admin": "系统管理员：全局权限与系统配置",
}


def user_has_any_role(user: User, roles: set[str]) -> bool:
    """True when the user holds at least one of ``roles``."""
    if user is None:
        return False
    return bool(roles.intersection({role.name for role in user.roles}))


def user_permissions(user: User) -> set[str]:
    codes: set[str] = set()
    for role in user.roles:
        codes.update(perm.code for perm in role.permissions)
        codes.update(ROLE_PERMISSIONS.get(role.name, []))
    return codes


def can(user: User, permission: str) -> bool:
    return permission in user_permissions(user)


def ensure_default_roles(session: Session) -> dict[str, Role]:
    """Create the five system roles and their permissions if missing."""
    from app.repositories import user_repo

    roles: dict[str, Role] = {}
    for name, codes in ROLE_PERMISSIONS.items():
        role = user_repo.ensure_role(session, name, ROLE_DESCRIPTIONS.get(name, ""), is_system=True)
        existing = {perm.code for perm in role.permissions}
        for code in codes:
            if code in existing:
                continue
            perm = session.scalar(select(Permission).where(Permission.code == code))
            if perm is None:
                perm = Permission(code=code, description=code)
                session.add(perm)
                session.flush()
            role.permissions.append(perm)
        roles[name] = role
    session.flush()
    return roles


def roles_for(session: Session, names: list[str]) -> list[Role]:
    from app.repositories import user_repo

    result: list[Role] = []
    for name in names:
        role = user_repo.ensure_role(session, name, ROLE_DESCRIPTIONS.get(name, ""), is_system=True)
        result.append(role)
    return result


def get_role_permissions(session: Session) -> dict[str, list[str]]:
    """Current role -> permission mapping as stored in the database."""
    roles = session.scalars(select(Role).order_by(Role.id)).all()
    return {role.name: sorted(p.code for p in role.permissions) for role in roles}


def assign_roles(session: Session, user: User, names: list[str]) -> User:
    user.roles = roles_for(session, names)
    session.flush()
    return user
