from typing import Dict, List, Optional
from models import Order, Store, SKU, LineItem

def find_substitute(sku: SKU, required_quantity: int, store_inventory: Dict[str, int],
                    all_skus: Dict[str, SKU], pref: str) -> Optional[str]:
    if pref == "NONE":
        return None

    candidates = []

    for cand_id, qty in store_inventory.items():
        if qty >= required_quantity and cand_id != sku.id:
            cand_sku = all_skus.get(cand_id)
            if not cand_sku:
                continue

            if pref == "SIMILAR_ONLY":
                if cand_sku.brand == sku.brand:
                    # Is there a price constraint on SIMILAR_ONLY?
                    # "a substituted line never costs more than the original" -> yes, final price will be capped.
                    # Wait, BR-05: "ALLOW permits any SKU in the same category with price within +15%... SIMILAR_ONLY permits only the same brand"
                    candidates.append(cand_sku)
            elif pref == "ALLOW":
                if cand_sku.category == sku.category and cand_sku.price <= sku.price * 1.15:
                    candidates.append(cand_sku)

    # Tie-breaker for multiple candidates:
    # 1. Price difference (closest to original price)
    # 2. Alphabetical by SKU ID
    if candidates:
        candidates.sort(key=lambda c: (abs(c.price - sku.price), c.id))
        return candidates[0].id

    return None

def process_substitutions(order: Order, store: Store, all_skus: Dict[str, SKU]):
    for item in order.line_items:
        sku = all_skus.get(item.sku_id)
        if not sku:
            continue

        available_qty = store.inventory.get(item.sku_id, 0)

        if available_qty >= item.quantity:
            # Full stock
            item.fulfilled_sku_id = item.sku_id
            item.fulfilled_quantity = item.quantity
            item.final_price = sku.price * item.quantity
        else:
            # Shortfall
            sub_id = find_substitute(sku, item.quantity, store.inventory, all_skus, order.substitution_preference)

            if sub_id:
                # Substituted
                sub_sku = all_skus[sub_id]
                item.fulfilled_sku_id = sub_id
                item.fulfilled_quantity = item.quantity

                # Customer pays original price or less
                unit_price = min(sku.price, sub_sku.price)
                item.final_price = unit_price * item.quantity

                # Deduct from inventory
                store.inventory[sub_id] -= item.quantity
            else:
                # Partial line
                item.fulfilled_sku_id = item.sku_id
                item.fulfilled_quantity = available_qty
                item.final_price = sku.price * available_qty

                if available_qty > 0:
                    store.inventory[item.sku_id] -= available_qty

def evaluate_partial_fulfillment(order: Order, all_skus: Dict[str, SKU]) -> bool:
    # Returns True if order is valid, False if it should be cancelled (< 60% value)
    original_value = sum(all_skus[item.sku_id].price * item.quantity for item in order.line_items if item.sku_id in all_skus)

    fulfilled_value = sum(item.final_price for item in order.line_items)

    if original_value > 0 and fulfilled_value < 0.6 * original_value:
        order.status = "CANCELLED"
        # "full refund and no delivery fee"
        return False

    return True

def calculate_delivery_fee(order: Order, store: Store):
    fulfilled_value = sum(item.final_price for item in order.line_items)

    if fulfilled_value >= 199.0:
        fee = 0.0
    else:
        fee = 25.0

    if store.active_riders < 3:
        fee += 15.0

    order.delivery_fee = fee
