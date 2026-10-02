"""Demo seed data.

    cd backend && python -m app.seed

Everything created here is fictional: fake product names, ``@example.com``
addresses and obviously-demo passwords.  Re-running is safe — every step is
get-or-create.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.db import SessionLocal, init_db
from app.models.product import SpuType
from app.models.warehouse import WarehouseType
from app.repositories import inventory_repo, product_repo, user_repo, warehouse_repo
from app.schemas.inventory import InventoryAdjustRequest
from app.schemas.product import BundleComponentIn, BundleSetRequest, SkuCreate, SpuCreate
from app.services import (
    auth_service,
    combo_service,
    inventory_service,
    permission_service,
    product_service,
    warehouse_service,
)

DEMO_USERS = [
    ("admin", "admin123", "owner", "系统管理员"),  # noqa: S105 - demo only
    ("operator", "operator123", "operator", "运营小周"),  # noqa: S105
    ("buyer", "buyer123", "buyer", "采购小吴"),  # noqa: S105
    ("warehouse", "warehouse123", "warehouse", "仓库小郑"),  # noqa: S105
]

WAREHOUSES = [
    ("WH-MAIN", "总仓", WarehouseType.MAIN, ["A-01", "A-02", "B-01", "C-01"]),
    ("WH-LIVE", "直播间仓", WarehouseType.LIVE, ["L-01", "L-02"]),
    ("WH-RETURN", "退货仓", WarehouseType.RETURN, ["R-01"]),
]

# (code, name, type, category, brand)
SPUS = [
    ("TSHIRT", "纯棉短袖", SpuType.SINGLE, "服饰", "示例品牌"),
    ("SHAMPOO", "清爽洗发水 500ml", SpuType.SINGLE, "个护", "示例品牌"),
    ("CONDITIONER", "柔顺护发素 500ml", SpuType.SINGLE, "个护", "示例品牌"),
    ("GIFT-SET", "洗护套装（洗发水+护发素）", SpuType.BUNDLE, "个护", "示例品牌"),
]

# (spu code, sku code, spec, barcode, purchase price cents, safety, initial stock)
SKUS = [
    ("TSHIRT", "TSHIRT-WHITE-L", {"color": "白", "size": "L"}, "690000000001", 3200, 5, 60),
    ("TSHIRT", "TSHIRT-WHITE-M", {"color": "白", "size": "M"}, "690000000002", 3200, 5, 40),
    ("TSHIRT", "TSHIRT-BLACK-L", {"color": "黑", "size": "L"}, "690000000003", 3200, 5, 25),
    ("SHAMPOO", "SHAMPOO-500", {"volume": "500ml"}, "690000000101", 1800, 10, 120),
    ("CONDITIONER", "CONDITIONER-500", {"volume": "500ml"}, "690000000201", 1900, 10, 90),
]

BUNDLE_SKU = "GIFT-SET-01"
BUNDLE_COMPONENTS = [("SHAMPOO-500", 1), ("CONDITIONER-500", 1)]


def _ensure_users(session: Session) -> None:
    for username, password, role, full_name in DEMO_USERS:
        if user_repo.get_by_username(session, username) is not None:
            continue
        user_repo.create(
            session,
            username=username,
            hashed_password=hash_password(password),
            email=f"{username}@example.com",
            full_name=full_name,
            roles=permission_service.roles_for(session, [role]),
        )
    session.commit()


def _ensure_warehouses(session: Session) -> dict[str, int]:
    ids: dict[str, int] = {}
    for code, name, type_, locations in WAREHOUSES:
        warehouse = warehouse_repo.get_by_code(session, code)
        if warehouse is None:
            warehouse = warehouse_repo.create(session, code=code, name=name, type=type_)
        ids[code] = warehouse.id
        for loc_code in locations:
            if warehouse_repo.get_location_by_code(session, warehouse.id, loc_code) is None:
                warehouse_repo.create_location(
                    session,
                    warehouse_id=warehouse.id,
                    code=loc_code,
                    name=f"{loc_code} 库位",
                    zone=loc_code.split("-")[0],
                )
    session.commit()
    return ids


def _ensure_spus(session: Session) -> dict[str, int]:
    ids: dict[str, int] = {}
    for code, name, type_, category, brand in SPUS:
        spu = product_repo.get_spu_by_code(session, code)
        if spu is None:
            spu = product_service.create_spu(
                session,
                SpuCreate(code=code, name=name, type=type_, category=category, brand=brand),
            )
        ids[code] = spu.id
    return ids


def _ensure_skus(session: Session, spu_ids: dict[str, int]) -> dict[str, int]:
    ids: dict[str, int] = {}
    for spu_code, sku_code, spec, barcode, price, safety, _stock in SKUS:
        sku = product_repo.get_sku_by_code(session, sku_code)
        if sku is None:
            sku = product_service.create_sku(
                session,
                spu_ids[spu_code],
                SkuCreate(
                    sku_code=sku_code,
                    spec_json=spec,
                    barcode=barcode,
                    purchase_price_cents=price,
                    safety_qty=safety,
                    weight_g=500,
                    package_spec="标准包装",
                ),
            )
        ids[sku_code] = sku.id

    bundle = product_repo.get_sku_by_code(session, BUNDLE_SKU)
    if bundle is None:
        bundle = product_service.create_sku(
            session,
            spu_ids["GIFT-SET"],
            SkuCreate(
                sku_code=BUNDLE_SKU,
                spec_json={"type": "套装"},
                barcode="690000000301",
                safety_qty=0,
                package_spec="礼盒装",
            ),
        )
    ids[BUNDLE_SKU] = bundle.id
    return ids


def _ensure_bundle(session: Session, sku_ids: dict[str, int]) -> None:
    if combo_service.component_pairs(session, sku_ids[BUNDLE_SKU]):
        return
    combo_service.set_components(
        session,
        sku_ids[BUNDLE_SKU],
        BundleSetRequest(
            components=[
                BundleComponentIn(component_sku_id=sku_ids[code], quantity=qty)
                for code, qty in BUNDLE_COMPONENTS
            ]
        ),
    )


def _seed_opening_stock(session: Session, sku_ids: dict[str, int], warehouse_ids: dict[str, int]) -> None:
    """Book opening balances as explicit ledger rows, never raw numbers."""
    main = warehouse_ids["WH-MAIN"]
    for _spu_code, sku_code, _spec, _barcode, _price, _safety, qty in SKUS:
        if qty <= 0:
            continue
        sku_id = sku_ids[sku_code]
        stock = inventory_repo.get_stock(session, sku_id, main)
        if stock is not None and stock.on_hand_qty > 0:
            continue
        inventory_service.adjust(
            session,
            InventoryAdjustRequest(
                sku_id=sku_id,
                warehouse_id=main,
                qty_delta=qty,
                reason="期初建账（演示数据）",
                idempotency_key=f"seed:{sku_code}",
            ),
            operator_id=None,
        )

    # Move a little stock into the live-stream warehouse so multi-warehouse
    # views have something real to show.
    for sku_code, qty in (("TSHIRT-WHITE-L", 12), ("SHAMPOO-500", 20)):
        inventory_service.adjust(
            session,
            InventoryAdjustRequest(
                sku_id=sku_ids[sku_code],
                warehouse_id=warehouse_ids["WH-LIVE"],
                qty_delta=qty,
                reason="期初建账（直播间仓）",
                idempotency_key=f"seed-live:{sku_code}",
            ),
            operator_id=None,
        )
    session.commit()


def main() -> None:
    init_db()
    session = SessionLocal()
    try:
        permission_service.ensure_default_roles(session)
        auth_service.bootstrap_admin(session)
        _ensure_users(session)
        warehouse_ids = _ensure_warehouses(session)
        spu_ids = _ensure_spus(session)
        sku_ids = _ensure_skus(session, spu_ids)
        _ensure_bundle(session, sku_ids)
        _seed_opening_stock(session, sku_ids, warehouse_ids)

        print("种子数据已写入：")
        print(f"  仓库 {len(WAREHOUSES)} 个 · SPU {len(SPUS)} 个 · SKU {len(sku_ids)} 个")
        print(f"  数据库 {settings.DATABASE_URL}")
        print("  演示账号（仅本地使用）：")
        for username, password, role, _name in DEMO_USERS:
            print(f"    {username:10s} / {password:14s} -> {role}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
