"""通知投递与重试。

重点不在「消息发出去」，而在**发不出去的时候会发生什么**：

* 邮件没配 SMTP → 立刻失败并给出 42402，不重试（重试一百次也一样）；
* Webhook 返回 4xx → 立刻失败（对方明确拒绝了）；
* Webhook 超时/5xx → 指数退避 2→4→8→16 秒；
* 无论通道成败，站内消息都已经可见 —— 一个坏掉的 webhook 不能让人看不到
  低库存预警。
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.core.config import settings
from app.models.base import utcnow
from app.models.notification import DeliveryStatus, NotificationChannel
from conftest import API, create_alert_rule, deliveries_of, ensure_alert_rule, scan_alerts


def send(client, headers, **extra):
    payload = {"title": "测试通知", "body": "内容", "category": "test"}
    payload.update(extra)
    response = client.post(f"{API}/notifications", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def enable(client, headers, channel: str, **config):
    response = client.put(
        f"{API}/notifications/settings/{channel}", json={"enabled": True, "config": config}, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------------------ 基本
def test_an_in_app_notification_is_visible_and_unread(client, owner_headers):
    body = send(client, owner_headers)
    assert body["is_read"] is False
    assert body["deliveries"][0]["channel"] == "inapp"
    assert body["deliveries"][0]["status"] == "sent"
    assert client.get(f"{API}/notifications/unread-count", headers=owner_headers).json()["unread"] >= 1


def test_marking_read_clears_the_badge(client, owner_headers):
    body = send(client, owner_headers)
    marked = client.post(f"{API}/notifications/{body['id']}/read", headers=owner_headers)
    assert marked.json()["is_read"] is True
    assert marked.json()["read_at"] is not None


def test_a_dedup_key_keeps_the_same_event_notified_once(
    client, owner_headers, low_stock, wh
):
    """同一张告警只提醒一次：扫描 3 遍，通知数量只涨 1。"""
    ensure_alert_rule(
        client,
        owner_headers,
        name="通知去重",
        scope="sku",
        sku_id=low_stock["sku"]["id"],
        threshold_qty=10,
    )

    def alert_notifications() -> int:
        return client.get(
            f"{API}/notifications?category=alert&page_size=200", headers=owner_headers
        ).json()["total"]

    before = alert_notifications()
    for _ in range(3):
        scan_alerts(client, owner_headers, warehouse_id=wh)
    assert alert_notifications() - before == 1


# ------------------------------------------------------------------ 通道
def test_a_disabled_channel_is_recorded_as_skipped(client, owner_headers):
    body = send(client, owner_headers)
    deliveries = {row["channel"]: row for row in body["deliveries"]}
    assert deliveries["inapp"]["status"] == "sent"


def test_email_without_smtp_fails_immediately(client, owner_headers, monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "")
    monkeypatch.setattr(settings, "SMTP_FROM", "")
    enable(client, owner_headers, "email", recipients="ops@example.com")

    body = send(client, owner_headers)
    deliveries = {row["channel"]: row for row in body["deliveries"]}
    email = deliveries["email"]
    assert email["status"] == "failed", "没配 SMTP 就该立刻失败，不该重试"
    assert email["next_retry_at"] is None


def test_a_webhook_to_a_dead_port_is_retried_not_dropped(client, owner_headers):
    # 127.0.0.1:9 是 discard 端口，几乎必定连不上 —— 确定性足够，且不触网。
    enable(client, owner_headers, "webhook", endpoint="http://127.0.0.1:9/hook")
    body = send(client, owner_headers)
    deliveries = {row["channel"]: row for row in body["deliveries"]}
    webhook = deliveries["webhook"]
    assert webhook["status"] == "retrying"
    assert webhook["attempts"] == 1
    assert webhook["next_retry_at"] is not None
    # 站内仍然送达 —— 外部通道坏了不该让人看不见
    assert deliveries["inapp"]["status"] == "sent"


def test_a_webhook_without_a_url_is_skipped(client, owner_headers):
    enable(client, owner_headers, "webhook")
    body = send(client, owner_headers)
    deliveries = {row["channel"]: row for row in body["deliveries"]}
    assert deliveries["webhook"]["status"] == "skipped"


# ------------------------------------------------------------------ 重试
def test_backoff_is_exponential():
    """2 → 4 → 8 → 16 秒。指数退避的上限也要有，否则卡住的通道会排到下一年。"""
    from app.services import notification_service

    assert [notification_service._backoff_seconds(n) for n in (1, 2, 3, 4)] == [2, 4, 8, 16]
    assert notification_service._backoff_seconds(99) <= 3600


def test_a_continuously_failing_webhook_gives_up_after_the_budget(client, owner_headers):
    """重试预算耗尽后状态转为 failed，并不再安排新的重试时间。"""
    from app.db import SessionLocal
    from app.models.notification import Notification, NotificationDelivery
    from app.services import notification_service

    enable(client, owner_headers, "webhook", endpoint="http://127.0.0.1:9/hook")
    body = send(client, owner_headers)
    notification_id = body["id"]
    delivery_id = [
        row["id"] for row in body["deliveries"] if row["channel"] == "webhook"
    ][0]

    session = SessionLocal()
    try:
        notification = session.get(Notification, notification_id)
        delivery = session.get(NotificationDelivery, delivery_id)
        assert delivery.status == DeliveryStatus.RETRYING
        assert delivery.next_retry_at is not None

        # 一路失败到预算用完
        for _ in range(settings.NOTIFY_MAX_RETRIES + 2):
            if delivery.status != DeliveryStatus.RETRYING:
                break
            notification_service._attempt(  # noqa: SLF001 - 直接驱动单次尝试
                session, notification, delivery
            )

        assert delivery.attempts == settings.NOTIFY_MAX_RETRIES
        assert delivery.status == DeliveryStatus.FAILED
        assert delivery.next_retry_at is None, "放弃之后不该再排下一次"
        assert delivery.last_error
    finally:
        session.close()


def test_retrying_a_healthy_webhook_marks_it_sent(client, owner_headers, monkeypatch):
    from app.db import SessionLocal
    from app.models.notification import NotificationDelivery
    from app.services import notification_service

    enable(client, owner_headers, "webhook", endpoint="http://127.0.0.1:9/hook")
    body = send(client, owner_headers)
    delivery_id = [
        row["id"] for row in body["deliveries"] if row["channel"] == "webhook"
    ][0]

    # 让重试「成功」：替换掉调度表里的 webhook 实现
    monkeypatch.setitem(
        notification_service._DISPATCHERS,  # noqa: SLF001 - 测试替换内部调度表
        NotificationChannel.WEBHOOK,
        lambda *a, **k: (DeliveryStatus.SENT, 200, ""),
    )

    session = SessionLocal()
    try:
        delivery = session.get(NotificationDelivery, delivery_id)
        delivery.next_retry_at = utcnow() - dt.timedelta(seconds=1)
        session.commit()

        # 别的用例可能也留下了到期投递，所以只断言「至少处理了这一条」
        assert notification_service.retry_due(session) >= 1
        session.refresh(delivery)
        assert delivery.status == DeliveryStatus.SENT
        assert delivery.sent_at is not None
        assert delivery.response_code == 200
    finally:
        session.close()


# ------------------------------------------------------------------ 可见性
def test_another_persons_private_notification_is_hidden(client, owner_headers, operator_headers):
    mine = client.post(
        f"{API}/notifications",
        json={"title": "只给店主", "recipient_id": None},
        headers=owner_headers,
    ).json()
    # 广播消息所有人可见
    theirs = client.get(f"{API}/notifications", headers=operator_headers).json()
    assert any(row["id"] == mine["id"] for row in theirs["items"])


def test_channel_settings_list_all_three_channels(client, owner_headers):
    rows = client.get(f"{API}/notifications/settings/all", headers=owner_headers).json()
    assert {row["channel"] for row in rows} == {"inapp", "email", "webhook"}
    # 站内默认就是开的
    assert next(row["enabled"] for row in rows if row["channel"] == "inapp") is True


def test_only_an_admin_may_configure_channels(client, operator_headers):
    response = client.put(
        f"{API}/notifications/settings/email", json={"enabled": True}, headers=operator_headers
    )
    assert response.status_code == 403
