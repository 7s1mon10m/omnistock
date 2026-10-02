"""退货单的状态流转规则。

抽成纯函数是因为「什么状态下能做什么」最容易被散落在各个接口里写成
if-else，然后彼此不一致。集中在这里，状态机就只有一份真相。
"""

from __future__ import annotations

from app.models.return_order import ReturnStatus

#: 哪些状态还能往下走；终态（inbound / cancelled）不能再动。
ALLOWED_TRANSITIONS: dict[ReturnStatus, tuple[ReturnStatus, ...]] = {
    ReturnStatus.PENDING: (ReturnStatus.INSPECTED, ReturnStatus.CANCELLED),
    ReturnStatus.INSPECTED: (ReturnStatus.INBOUND, ReturnStatus.CANCELLED),
    ReturnStatus.INBOUND: (),
    ReturnStatus.CANCELLED: (),
}


def can_transition(current: ReturnStatus, target: ReturnStatus) -> bool:
    """是否允许从 ``current`` 走到 ``target``。

    自己走到自己一律不允许 —— 「重复入库」是最容易把库存做double的一条路，
    必须显式拒绝，而不是让它变成一次无害的空操作。
    """
    if current == target:
        return False
    return target in ALLOWED_TRANSITIONS.get(current, ())


def describe(current: ReturnStatus) -> str:
    """给报错用的可读说明。"""
    allowed = ALLOWED_TRANSITIONS.get(current, ())
    if not allowed:
        return f"退货单已处于终态 {current.value}，不能再变更"
    names = ", ".join(status.value for status in allowed)
    return f"当前状态 {current.value} 只允许：{names}"


def require(current: ReturnStatus, target: ReturnStatus) -> None:
    from app.core.errors import RETURN_ORDER_INVALID_TRANSITION, BusinessError

    if not can_transition(current, target):
        raise BusinessError(
            RETURN_ORDER_INVALID_TRANSITION, describe(current), http_status=409
        )
