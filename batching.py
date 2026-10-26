from typing import List, Optional
from models import Order, Batch, Rider
from allocation import calculate_haversine
from datetime import datetime, timedelta

def is_batchable(order: Order, batch: Batch) -> bool:
    if len(batch.orders) >= 3:
        return False

    # Check if drop points are within 1.0 km of each other
    for existing_order in batch.orders:
        dist = calculate_haversine(
            order.customer_lat, order.customer_lon,
            existing_order.customer_lat, existing_order.customer_lon
        )
        if dist > 1.0:
            return False

    # Check if baseline promised ETAs differ by at most 4 min
    # Baseline ETA is the ETA as if the order was the first in the batch
    from allocation import calculate_eta
    store = next((s for s in batch.orders), None) # Need store to compute ETA, actually we have store_id.
    # Wait, `is_batchable` receives `order` which already has `promised_eta` computed at seq=0.
    # The existing orders in the batch have `promised_eta` which might be computed at seq>0.
    # BUT wait, in `engine.py`, `order.promised_eta` is recalculated *after* batching.
    # At the time `is_batchable` is called, `existing_order.promised_eta` might be the shifted one?
    # No, we must use the base ETA difference. Let's recalculate base ETA for comparison.
    # Actually, in `engine.py`, we assign `order.promised_eta = calculate_eta(..., seq=0)` BEFORE batching.
    # BUT for existing orders, their `promised_eta` was already updated to `calculate_eta(..., seq=seq)`.
    # BR-08 says "whose baseline promised ETAs differ by at most 4 min".
    # So we need to subtract (2 min * sequence) from existing orders' promised_eta to get baseline.

    for i, existing_order in enumerate(batch.orders):
        # Reverse the batch sequence shift to get baseline ETA
        baseline_existing_eta = existing_order.promised_eta - timedelta(minutes=2 * i)
        # The new order's promised_eta is currently at seq=0 (baseline)
        diff_seconds = abs((order.promised_eta - baseline_existing_eta).total_seconds())
        if diff_seconds > 4 * 60:
            return False

    return True

def assign_to_batch(order: Order, active_batches: List[Batch], current_time: datetime, generate_id_fn) -> Batch:
    # Try to find an existing batch
    for batch in active_batches:
        if is_batchable(order, batch):
            batch.orders.append(order)
            order.batch_id = batch.id
            return batch

    # Create new batch if none found
    new_batch = Batch(
        id=generate_id_fn(),
        store_id=order.store_id,
        orders=[order],
        rider_id=None,
        dispatch_time=None
    )
    order.batch_id = new_batch.id
    active_batches.append(new_batch)
    return new_batch

def check_batch_dispatch(batch: Batch, current_time: datetime) -> bool:
    if not batch.orders:
        return False

    if len(batch.orders) == 3:
        return True

    # Dispatch if 3 min after its first order was picked
    # When is an order "picked"? Let's assume order.allocated_slot + 2 min picking time
    # The rule says: "3 min after its first order was picked"
    # This means wait 3 min after picking is finished? Or after it was placed?
    # "a batch dispatches when full or 3 min after its first order was picked"
    # Wait, the ETA formula says "2 min pick". So picking finishes at base_time + 2 min.
    # So dispatch time is base_time + 2 min + 3 min = base_time + 5 min.

    first_order = batch.orders[0]
    base_time = first_order.allocated_slot if first_order.allocated_slot else first_order.timestamp
    pick_time = base_time + timedelta(minutes=2)
    dispatch_timeout = pick_time + timedelta(minutes=3)

    if current_time >= dispatch_timeout:
        return True

    return False
