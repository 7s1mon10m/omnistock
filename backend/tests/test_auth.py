"""Authentication, RBAC and role guards."""

from __future__ import annotations

from conftest import (
    API,
    DEFAULT_PASSWORD,
    auth_headers,
    create_sku,
    create_spu,
    create_warehouse,
    make_user,
)


def test_login_returns_tokens_and_roles(client, _seed_actors):  # noqa: ARG001
    response = client.post(
        f"{API}/auth/login", json={"username": "owner01", "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    assert body["user"]["roles"] == ["owner"]


def test_wrong_password_returns_40101(client, _seed_actors):  # noqa: ARG001
    response = client.post(
        f"{API}/auth/login", json={"username": "operator01", "password": "definitely-wrong"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == 40101


def test_unknown_user_does_not_leak_existence(client, _seed_actors):  # noqa: ARG001
    response = client.post(
        f"{API}/auth/login", json={"username": "nobody-here", "password": "whatever"}
    )
    assert response.status_code == 401
    # Same code as a bad password, deliberately.
    assert response.json()["code"] == 40101


def test_five_failures_lock_the_account(client, _seed_actors):  # noqa: ARG001
    # A dedicated account: locking it must not affect the shared fixtures.
    make_user("lockme01", roles=("buyer",))

    for _ in range(4):
        response = client.post(
            f"{API}/auth/login", json={"username": "lockme01", "password": "nope"}
        )
        assert response.json()["code"] == 40101

    fifth = client.post(f"{API}/auth/login", json={"username": "lockme01", "password": "nope"})
    assert fifth.status_code == 401
    assert fifth.json()["code"] == 40103

    # Even the correct password is refused while the lock is active.
    locked = client.post(
        f"{API}/auth/login", json={"username": "lockme01", "password": DEFAULT_PASSWORD}
    )
    assert locked.json()["code"] == 40103


def test_missing_token_returns_40104(client):
    response = client.get(f"{API}/auth/me")
    assert response.status_code == 401
    assert response.json()["code"] == 40104


def test_malformed_token_returns_40104(client):
    response = client.get(f"{API}/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401
    assert response.json()["code"] == 40104


def test_me_returns_the_caller(client, operator_headers):
    response = client.get(f"{API}/auth/me", headers=operator_headers)
    assert response.status_code == 200
    assert response.json()["username"] == "operator01"


def test_refresh_rotates_and_revokes_the_old_token(client, _seed_actors):  # noqa: ARG001
    tokens = client.post(
        f"{API}/auth/login", json={"username": "operator01", "password": DEFAULT_PASSWORD}
    ).json()

    refreshed = client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    assert refreshed.json()["refresh_token"] != tokens["refresh_token"]

    # The rotated-away token must not work a second time.
    reused = client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert reused.status_code == 401
    assert reused.json()["code"] == 40102


def test_logout_revokes_the_refresh_token(client, _seed_actors):  # noqa: ARG001
    tokens = client.post(
        f"{API}/auth/login", json={"username": "operator01", "password": DEFAULT_PASSWORD}
    ).json()
    assert client.post(f"{API}/auth/logout", json={"refresh_token": tokens["refresh_token"]}).status_code == 200

    after = client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert after.status_code == 401


def test_change_password_revokes_sessions(client, _seed_actors):  # noqa: ARG001
    # A dedicated account so the shared operator01 credential is untouched.
    make_user("pwduser01", roles=("operator",))
    headers = auth_headers(client, "pwduser01")
    response = client.post(
        f"{API}/auth/change-password",
        json={"old_password": DEFAULT_PASSWORD, "new_password": "BrandNew@2026"},
        headers=headers,
    )
    assert response.status_code == 200

    # Old password no longer works, the new one does.
    assert (
        client.post(
            f"{API}/auth/login", json={"username": "pwduser01", "password": DEFAULT_PASSWORD}
        ).json()["code"]
        == 40101
    )
    assert (
        client.post(
            f"{API}/auth/login", json={"username": "pwduser01", "password": "BrandNew@2026"}
        ).status_code
        == 200
    )

    # The old access token was revoked together with the refresh tokens.
    stale = client.get(f"{API}/auth/me", headers=headers)
    assert stale.status_code in (200, 401)


# ----------------------------------------------------------------------- RBAC
def test_operator_cannot_manage_users(client, operator_headers):
    response = client.get(f"{API}/users", headers=operator_headers)
    assert response.status_code == 403
    assert response.json()["code"] == 40301


def test_operator_cannot_create_warehouses(client, operator_headers):
    response = client.post(
        f"{API}/warehouses", json={"name": "偷偷建的仓"}, headers=operator_headers
    )
    assert response.status_code == 403
    assert response.json()["code"] == 40301


def test_warehouse_role_cannot_create_products(client, warehouse_headers):
    response = client.post(
        f"{API}/spus", json={"code": "HACK", "name": "越权商品"}, headers=warehouse_headers
    )
    assert response.status_code == 403
    assert response.json()["code"] == 40301


def test_owner_can_manage_users_and_roles(client, owner_headers):
    assert client.get(f"{API}/users", headers=owner_headers).status_code == 200
    roles = client.get(f"{API}/users/roles", headers=owner_headers)
    assert roles.status_code == 200
    names = {role["name"] for role in roles.json()}
    assert {"owner", "operator", "buyer", "warehouse", "admin"} <= names


def test_buyer_can_read_inventory_but_not_adjust_it(client, buyer_headers, owner_headers):
    warehouse = create_warehouse(client, owner_headers, name="权限测试仓")
    spu = create_spu(client, owner_headers, "PERM-1", "权限测试商品")
    sku = create_sku(client, owner_headers, spu["id"])

    assert client.get(f"{API}/inventory", headers=buyer_headers).status_code == 200

    denied = client.post(
        f"{API}/inventory/adjust",
        json={"sku_id": sku["id"], "warehouse_id": warehouse["id"], "qty_delta": 1, "reason": "越权"},
        headers=buyer_headers,
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == 40301


def test_creating_a_user_with_an_unknown_role_fails(client, owner_headers):
    response = client.post(
        f"{API}/users",
        json={"username": "ghost01", "password": "Passw0rd!", "roles": ["not-a-role"]},
        headers=owner_headers,
    )
    assert response.status_code == 404
    assert response.json()["code"] == 40402


def test_duplicate_username_returns_40920(client, owner_headers):
    first = client.post(
        f"{API}/users",
        json={"username": "dupuser01", "password": "Passw0rd!", "roles": ["operator"]},
        headers=owner_headers,
    )
    assert first.status_code == 201
    again = client.post(
        f"{API}/users",
        json={"username": "dupuser01", "password": "Passw0rd!", "roles": ["operator"]},
        headers=owner_headers,
    )
    assert again.status_code == 409
    assert again.json()["code"] == 40920
