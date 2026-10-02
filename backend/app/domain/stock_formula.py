"""The stock arithmetic, kept pure so it can be unit-tested in isolation.

    可售库存 = 实际库存 - 已占用库存 - 安全库存
"""

from __future__ import annotations


def available_qty(on_hand: int, reserved: int, safety: int) -> int:
    """How many units may still be sold.

    Note the safety buffer is subtracted, so it is never sellable.  This is the
    single definition used by the API, the ledger checks and the alert scanner.
    """
    return on_hand - reserved - safety


def is_low_stock(on_hand: int, reserved: int, safety: int, in_transit: int = 0) -> bool:
    """True when sellable plus inbound stock has fallen below the buffer."""
    return available_qty(on_hand, reserved, safety) + in_transit < safety


def next_on_hand(on_hand: int, qty_delta: int) -> int:
    return on_hand + qty_delta


def buildable_bundles(component_availability: list[tuple[int, int]]) -> int:
    """How many complete bundles the given component stock supports.

    ``component_availability`` is a list of ``(available_qty, per_bundle_qty)``.
    Returns the minimum whole number of bundles that can be assembled, or 0 when
    the list is empty.
    """
    if not component_availability:
        return 0
    caps: list[int] = []
    for available, per_bundle in component_availability:
        if per_bundle <= 0:
            return 0
        caps.append(available // per_bundle)
    return max(0, min(caps))
