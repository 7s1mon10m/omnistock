"""Bundle explosion math.

A bundle (组合商品) is sold as one line but consumes several component SKUs: an
order for 3 sets of "洗发水 + 护发素" reserves 3 shampoo and 3 conditioner units.
"""

from __future__ import annotations


def explode(components: list[tuple[int, int]], quantity: int) -> list[tuple[int, int]]:
    """Expand ``(component_sku_id, per_bundle_qty)`` into required quantities.

    Returns ``[(component_sku_id, required_qty), ...]`` with zero-quantity rows
    dropped, so callers never have to special-case an empty component list.
    """
    if quantity <= 0:
        return []
    required: list[tuple[int, int]] = []
    for component_sku_id, per_bundle in components:
        need = per_bundle * quantity
        if need > 0:
            required.append((component_sku_id, need))
    return required


def merge_requirements(rows: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge duplicate SKU rows, which happens when a bundle repeats a SKU."""
    totals: dict[int, int] = {}
    order: list[int] = []
    for sku_id, qty in rows:
        if sku_id not in totals:
            totals[sku_id] = 0
            order.append(sku_id)
        totals[sku_id] += qty
    return [(sku_id, totals[sku_id]) for sku_id in order if totals[sku_id] > 0]
