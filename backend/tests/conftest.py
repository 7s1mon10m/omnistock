"""Shared pytest fixtures.

The database URL is pinned to a throw-away SQLite file *before* the application
is imported, so running the suite never touches a developer's local database.
"""

from __future__ import annotations

import itertools
import os
import tempfile

_TMP_DIR = tempfile.mkdtemp(prefix="omnistock-test-")
_DB_PATH = os.path.join(_TMP_DIR, "test.db").replace("\\", "/")

os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ["APP_ENV"] = "test"
os.environ["AUTH_SECRET_KEY"] = "test-only-secret-key-with-at-least-32-bytes"
os.environ["DEFAULT_ADMIN_PASSWORD"] = "Admin@12345"
os.environ["AUTH_MAX_LOGIN_ATTEMPTS"] = "5"
# Tests hash a lot of passwords; a low round count keeps the suite fast.  The
# production default stays at 120_000.
os.environ["AUTH_PBKDF2_ROUNDS"] = "1200"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from httpx import Response  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.repositories import user_repo  # noqa: E402
from app.services import permission_service  # noqa: E402

API = "/api/v1"
DEFAULT_PASSWORD = "Passw0rd!"

#: The only migration M1 ships.
HEAD_REVISION = "0001"


def _stamp_head_revision() -> None:
    """Mark the throw-away schema as fully migrated."""
    import sqlalchemy as sa

    from app.db import engine

    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE IF NOT EXISTS alembic_version "
                "(version_num VARCHAR(32) NOT NULL)"
            )
        )
        connection.execute(sa.text("DELETE FROM alembic_version"))
        connection.execute(
            sa.text("INSERT INTO alembic_version (version_num) VALUES (:head)"),
            {"head": HEAD_REVISION},
        )


# --------------------------------------------------------------------- fixtures
@pytest.fixture(scope="session", autouse=True)
def _schema() -> None:
    init_db()
    _stamp_head_revision()


@pytest.fixture(scope="session", autouse=True)
def _default_roles(_schema) -> None:
    session = SessionLocal()
    try:
        permission_service.ensure_default_roles(session)
        session.commit()
    finally:
        session.close()


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


# ----------------------------------------------------------------------- users
def make_user(
    username: str, password: str = DEFAULT_PASSWORD, roles: tuple[str, ...] = ("owner",)
) -> int:
    """Create a user with the given roles and return its id."""
    session = SessionLocal()
    try:
        permission_service.ensure_default_roles(session)
        existing = user_repo.get_by_username(session, username)
        if existing is not None:
            return existing.id
        user = user_repo.create(
            session,
            username=username,
            hashed_password=hash_password(password),
            email=f"{username}@example.com",
            full_name=username,
            roles=permission_service.roles_for(session, list(roles)),
        )
        session.commit()
        return user.id
    finally:
        session.close()


@pytest.fixture(scope="session", autouse=True)
def _seed_actors(_default_roles) -> None:
    """Guarantee the four personas exist regardless of test file order."""
    make_user("owner01", roles=("owner",))
    make_user("operator01", roles=("operator",))
    make_user("buyer01", roles=("buyer",))
    make_user("warehouse01", roles=("warehouse",))


def login(client: TestClient, username: str, password: str = DEFAULT_PASSWORD) -> dict:
    response = client.post(f"{API}/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def auth_headers(client: TestClient, username: str, password: str = DEFAULT_PASSWORD) -> dict[str, str]:
    payload = login(client, username, password)
    return {"Authorization": f"Bearer {payload['access_token']}"}


@pytest.fixture()
def owner_headers(client: TestClient) -> dict[str, str]:
    return auth_headers(client, "owner01")


@pytest.fixture()
def operator_headers(client: TestClient) -> dict[str, str]:
    return auth_headers(client, "operator01")


@pytest.fixture()
def buyer_headers(client: TestClient) -> dict[str, str]:
    return auth_headers(client, "buyer01")


@pytest.fixture()
def warehouse_headers(client: TestClient) -> dict[str, str]:
    return auth_headers(client, "warehouse01")


# ------------------------------------------------------------ domain factories
_counter = itertools.count(1)


def uniq(prefix: str) -> str:
    """A per-call suffix.

    Tests share one database for the whole session, so anything that must not
    collide (a warehouse code, a SKU code) goes through here.
    """
    return f"{prefix}{next(_counter):04d}"


def create_warehouse(
    client: TestClient,
    headers: dict[str, str],
    name: str = "测试总仓",
    code: str | None = None,
    type_: str = "main",
) -> dict:
    """Create a warehouse, or return the existing one when ``code`` is taken."""
    if code:
        listed = client.get(f"{API}/warehouses?keyword={code}&page_size=200", headers=headers).json()
        for item in listed["items"]:
            if item["code"] == code:
                return item

    payload: dict = {"name": name, "type": type_}
    if code:
        payload["code"] = code
    response = client.post(f"{API}/warehouses", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def create_spu(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    name: str,
    type_: str = "single",
) -> dict:
    listed = client.get(f"{API}/spus?keyword={code}&page_size=200", headers=headers).json()
    for item in listed["items"]:
        if item["code"] == code:
            return item

    response = client.post(
        f"{API}/spus",
        json={"code": code, "name": name, "type": type_},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_sku(client: TestClient, headers: dict[str, str], spu_id: int, **overrides) -> dict:
    """Create a SKU, or return the existing one when ``sku_code`` is taken."""
    wanted = overrides.get("sku_code")
    if wanted:
        listed = client.get(f"{API}/skus?keyword={wanted}&page_size=200", headers=headers).json()
        for item in listed["items"]:
            if item["sku_code"] == wanted and item["spu_id"] == spu_id:
                return item

    payload = {"spu_id": spu_id, "spec_json": {"size": "M"}, **overrides}
    response = client.post(f"{API}/skus", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def adjust_stock(
    client: TestClient,
    headers: dict[str, str],
    sku_id: int,
    warehouse_id: int,
    delta: int,
    reason: str = "测试调整",
    **extra,
) -> Response:
    return client.post(
        f"{API}/inventory/adjust",
        json={"sku_id": sku_id, "warehouse_id": warehouse_id, "qty_delta": delta,
              "reason": reason, **extra},
        headers=headers,
    )


def reserve_stock(
    client: TestClient, headers: dict[str, str], sku_id: int, warehouse_id: int, quantity: int, **extra
) -> Response:
    return client.post(
        f"{API}/inventory/reserve",
        json={"sku_id": sku_id, "warehouse_id": warehouse_id, "quantity": quantity, **extra},
        headers=headers,
    )


# ------------------------------------------------------- M2: channels & orders
def create_channel(
    client: TestClient,
    headers: dict[str, str],
    code: str | None = None,
    name: str = "测试渠道",
    platform: str = "taobao",
) -> dict:
    code = code or uniq("CH")
    listed = client.get(f"{API}/channels?keyword={code}&page_size=200", headers=headers).json()
    for item in listed["items"]:
        if item["code"] == code:
            return item
    response = client.post(
        f"{API}/channels", json={"code": code, "name": name, "platform": platform}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_shop(
    client: TestClient, headers: dict[str, str], channel_id: int, code: str | None = None
) -> dict:
    code = code or uniq("SH")
    response = client.post(
        f"{API}/channels/{channel_id}/shops", json={"code": code, "name": code}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_mapping(
    client: TestClient,
    headers: dict[str, str],
    channel_id: int,
    channel_product_code: str,
    sku_id: int,
    **extra,
) -> Response:
    return client.post(
        f"{API}/channel-products",
        json={
            "channel_id": channel_id,
            "channel_product_code": channel_product_code,
            "sku_id": sku_id,
            **extra,
        },
        headers=headers,
    )


def import_orders(
    client: TestClient, headers: dict[str, str], orders: list[dict], **extra
) -> Response:
    return client.post(
        f"{API}/orders/import-json",
        json={"source": "import_json", "filename": "test.json", "orders": orders, **extra},
        headers=headers,
    )


def order_payload(
    channel_code: str,
    channel_order_no: str,
    items: list[dict],
    *,
    shop_code: str | None = None,
    warehouse_code: str | None = None,
    buyer_nick: str = "测试买家",
    paid_at: str | None = None,
) -> dict:
    payload: dict = {
        "channel_code": channel_code,
        "channel_order_no": channel_order_no,
        "buyer_nick": buyer_nick,
        "items": items,
    }
    if shop_code:
        payload["shop_code"] = shop_code
    if warehouse_code:
        payload["warehouse_code"] = warehouse_code
    if paid_at:
        payload["paid_at"] = paid_at
    return payload


@pytest.fixture()
def catalog(client, owner_headers, monkeypatch):
    """A private warehouse with one plain SKU stocked to 100.

    Each call gets its own namespace (warehouse + SKU codes) so order tests never
    interfere with each other or with the inventory tests.  The warehouse is also
    made the *default* one, which is what an order without an explicit
    ``warehouse_code`` resolves to.
    """
    tag = uniq("CAT")
    warehouse = create_warehouse(client, owner_headers, name=f"目录仓{tag}", code=f"WH-{tag}")
    spu = create_spu(client, owner_headers, f"SPU-{tag}", "测试商品")
    sku = create_sku(client, owner_headers, spu["id"], sku_code=f"SKU-{tag}", safety_qty=0)
    adjust_stock(client, owner_headers, sku["id"], warehouse["id"], 100, "备货")
    monkeypatch.setattr(settings, "DEFAULT_WAREHOUSE_CODE", warehouse["code"])
    return {
        "warehouse": warehouse,
        "spu": spu,
        "sku": sku,
        "tag": tag,
        "headers": owner_headers,
    }


def stock_of(
    client: TestClient, headers: dict[str, str], sku_id: int, warehouse_id: int
) -> dict:
    rows = client.get(
        f"{API}/inventory?sku_id={sku_id}&page_size=200", headers=headers
    ).json()["items"]
    return next(row for row in rows if row["warehouse_id"] == warehouse_id)
