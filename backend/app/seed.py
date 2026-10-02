"""Demo seed data.

    cd backend && python -m app.seed

Everything created here is fictional: fake product names, ``@example.com``
addresses and obviously-demo passwords.  Re-running is safe — every step is
get-or-create.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.base import ParsedImport
from app.core.config import settings
from app.core.errors import BusinessError
from app.core.security import hash_password
from app.db import SessionLocal, init_db
from app.models.channel import ChannelPlatform
from app.models.order import OrderSource, SalesOrder
from app.models.product import SpuType
from app.models.warehouse import WarehouseType
from app.repositories import (
    channel_repo,
    inventory_repo,
    order_repo,
    product_repo,
    shipment_repo,
    user_repo,
    warehouse_repo,
)
from app.schemas.channel import ChannelCreate, ChannelProductCreate, ShopCreate
from app.schemas.inventory import InventoryAdjustRequest
from app.schemas.order import OrderIn, OrderItemIn
from app.schemas.product import BundleComponentIn, BundleSetRequest, SkuCreate, SpuCreate
from app.services import (
    auth_service,
    channel_service,
    combo_service,
    inventory_service,
    order_import_service,
    permission_service,
    product_service,
    shipment_service,
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

# --------------------------------------------------------------------- M2 data
# (code, name, platform)
CHANNELS = [
    ("TB", "淘宝", ChannelPlatform.TAOBAO),
    ("DY", "抖音", ChannelPlatform.DOUYIN),
    ("SHOP", "Shopify 独立站", ChannelPlatform.SHOPIFY),
]

# (channel code, shop code, shop name)
SHOPS = [
    ("TB", "TB-SHOP-1", "淘宝旗舰店"),
    ("DY", "DY-SHOP-1", "抖音小店"),
    ("SHOP", "SHOP-1", "独立站主站"),
]

# (channel code, external product code, internal sku code, title)
# The whole point: three different platform codes all resolve to the same
# internal SKU, so they share one stock pool.
MAPPINGS = [
    ("TB", "TB-100238", "TSHIRT-WHITE-L", "夏季纯棉短袖 白色 L"),
    ("TB", "TB-100239", "TSHIRT-WHITE-M", "夏季纯棉短袖 白色 M"),
    ("TB", "TB-100240", "TSHIRT-BLACK-L", "夏季纯棉短袖 黑色 L"),
    ("TB", "TB-100301", "GIFT-SET-01", "洗护套装 礼盒装"),
    ("DY", "DY-883021", "TSHIRT-WHITE-L", "短袖T恤 白 L"),
    ("DY", "DY-883101", "SHAMPOO-500", "清爽洗发水 500ml"),
    ("SHOP", "SHOP-TS-001", "TSHIRT-WHITE-L", "Cotton Tee / White / L"),
    ("SHOP", "SHOP-SET-001", "GIFT-SET-01", "Hair Care Gift Set"),
]

#: 总仓里每个 SKU 的固定拣货库位（M3）。拣货单按它排序，决定走货路线。
PICK_LOCATIONS = {
    "TSHIRT-WHITE-L": "A-01",
    "TSHIRT-WHITE-M": "A-01",
    "TSHIRT-BLACK-L": "A-02",
    "SHAMPOO-500": "B-01",
    "CONDITIONER-500": "B-01",
    "GIFT-SET-01": "C-01",
}

#: 演示用的拣货单来源订单（必须是一笔已占用库存的订单）。
DEMO_SHIPMENT_ORDER_NO = "TB202610020001"

# Demo orders so the console is not empty on first run.
# (channel, shop, order no, [(external code, qty, unit price cents)], buyer)
DEMO_ORDERS = [
    ("TB", "TB-SHOP-1", "TB202610020001", [("TB-100238", 2, 9900)], "张*三"),
    ("DY", "DY-SHOP-1", "DY202610020001", [("DY-883021", 1, 9500), ("DY-883101", 2, 5900)], "李*四"),
    ("SHOP", "SHOP-1", "SHOP-2026-0001", [("SHOP-SET-001", 3, 19900)], "王*五"),
    # A deliberately short order: 500 units against a much smaller stock.
    ("TB", "TB-SHOP-1", "TB202610020002", [("TB-100240", 500, 9900)], "赵*六"),
]


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


def _ensure_channels(session: Session) -> dict[str, int]:
    ids: dict[str, int] = {}
    for code, name, platform in CHANNELS:
        channel = channel_repo.get_channel_by_code(session, code)
        if channel is None:
            channel = channel_service.create_channel(
                session, ChannelCreate(code=code, name=name, platform=platform)
            )
        ids[code] = channel.id

    for channel_code, shop_code, shop_name in SHOPS:
        channel_id = ids[channel_code]
        if channel_repo.get_shop_by_code(session, channel_id, shop_code) is None:
            channel_service.create_shop(
                session, channel_id, ShopCreate(code=shop_code, name=shop_name)
            )
    return ids


def _ensure_mappings(session: Session, sku_ids: dict[str, int]) -> int:
    """Map every platform's own product code onto the shared internal SKUs."""
    for channel_code, external_code, sku_code, title in MAPPINGS:
        channel = channel_repo.get_channel_by_code(session, channel_code)
        sku_id = sku_ids.get(sku_code)
        if channel is None or sku_id is None:
            continue
        if channel_repo.get_mapping(session, channel.id, external_code) is not None:
            continue
        channel_service.create_mapping(
            session,
            ChannelProductCreate(
                channel_id=channel.id,
                channel_product_code=external_code,
                sku_id=sku_id,
                channel_title=title,
            ),
        )

    present = 0
    for channel_code, external_code, _sku_code, _title in MAPPINGS:
        channel = channel_repo.get_channel_by_code(session, channel_code)
        if channel is not None and channel_repo.get_mapping(session, channel.id, external_code):
            present += 1
    return present


def _ensure_demo_orders(session: Session) -> dict[str, int] | None:
    """Import a few orders, including one that lands in the exception queue.

    Runs through the real import pipeline, so the resulting ledger rows,
    reservations and exception records are exactly what production would produce.
    """
    existing = session.scalar(select(func.count()).select_from(SalesOrder)) or 0
    if existing:
        return None

    payloads = [
        OrderIn(
            channel_code=channel_code,
            shop_code=shop_code,
            channel_order_no=order_no,
            buyer_nick=buyer,
            items=[
                OrderItemIn(
                    channel_product_code=code, quantity=qty, unit_price_cents=price_yuan * 100
                )
                for code, qty, price_yuan in items
            ],
        )
        for channel_code, shop_code, order_no, items, buyer in DEMO_ORDERS
    ]

    result = order_import_service.import_orders(
        session,
        ParsedImport(orders=payloads),
        source=OrderSource.IMPORT_JSON,
        filename="seed-demo-orders.json",
        operator_id=None,
    )
    return {
        "created": result.created_orders,
        "reserved": result.reserved_orders,
        "exception": result.exception_orders,
    }


def _assign_pick_locations(session: Session, sku_ids: dict[str, int], warehouse_ids: dict[str, int]) -> int:
    """Give every demo SKU a standing bin, which is what makes pick lists walkable."""
    main = warehouse_ids["WH-MAIN"]
    assigned = 0
    for sku_code, location_code in PICK_LOCATIONS.items():
        sku_id = sku_ids.get(sku_code)
        if sku_id is None:
            continue
        location = warehouse_repo.get_location_by_code(session, main, location_code)
        if location is None:
            continue
        stock = inventory_repo.get_stock(session, sku_id, main)
        if stock is None or stock.default_location_id == location.id:
            continue
        stock.default_location_id = location.id
        assigned += 1
    session.commit()
    return assigned


def _ensure_demo_shipment(session: Session) -> str | None:
    """Open a pick list for one demo order so the workbench is not empty."""
    channel = channel_repo.get_channel_by_code(session, "TB")
    if channel is None:
        return None
    order = order_repo.get_order_by_channel_no(session, channel.id, DEMO_SHIPMENT_ORDER_NO)
    if order is None:
        return None

    existing = shipment_repo.get_active_by_order(session, order.id)
    if existing is not None:
        return existing.shipment_no

    try:
        shipment = shipment_service.create_shipment(session, order, remark="演示：待拣货")
    except BusinessError:
        return None
    return shipment.shipment_no


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
        _ensure_channels(session)
        mapping_count = _ensure_mappings(session, sku_ids)
        order_stats = _ensure_demo_orders(session)
        location_count = _assign_pick_locations(session, sku_ids, warehouse_ids)
        shipment_no = _ensure_demo_shipment(session)

        print("种子数据已写入：")
        print(
            f"  仓库 {len(WAREHOUSES)} 个 · SPU {len(SPUS)} 个 · SKU {len(sku_ids)} 个 · "
            f"渠道 {len(CHANNELS)} 个 · 渠道商品映射 {mapping_count} 条"
        )
        print(f"  已分配拣货库位 {location_count} 个 SKU（总仓）")
        if order_stats:
            print(
                f"  演示订单 {order_stats['created']} 笔"
                f"（已占用 {order_stats['reserved']} · 异常 {order_stats['exception']}）"
            )
        if shipment_no:
            print(f"  演示拣货单 {shipment_no}（状态：待拣货）")
        print(f"  数据库 {settings.DATABASE_URL}")
        print("  演示账号（仅本地使用）：")
        for username, password, role, _name in DEMO_USERS:
            print(f"    {username:10s} / {password:14s} -> {role}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
