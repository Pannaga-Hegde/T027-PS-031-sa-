from datetime import datetime
from models import Order, Rider, Batch

def calculate_sla_compensation(order: Order, actual_time: datetime):
    delay = (actual_time - order.promised_eta).total_seconds() / 60.0

    if delay > 0:
        if order.delayed_promise and delay <= 5.0:
            return

        if 5.0 <= delay <= 10.0:
            order.sla_compensation = 25.0
        elif delay > 10.0:
            order.sla_compensation = 50.0
            order.free_delivery_coupon = True

def calculate_rider_penalty(rider: Rider, batch: Batch, deliveries: list[tuple[Order, datetime]]):
    late_count = 0

    for order, actual_time in deliveries:
        delay = (actual_time - order.promised_eta).total_seconds() / 60.0
        if delay > 0:
            late_count += 1

        if delay > 15.0:
            if rider.daily_penalties < 90.0:
                rider.daily_penalties = min(90.0, rider.daily_penalties + 30.0)

    if late_count >= 2:
        pass # loses the 20 batch bonus (gets 0 for this batch)
    else:
        rider.daily_bonus += 20.0

def print_order_trace(order: Order, processor):
    print(f"--- Trace for Order {order.id} ---")
    print(f"Status: {order.status}")
    print(f"Store: {order.store_id}")
    if order.allocated_slot:
        print(f"Allocated Slot: {order.allocated_slot.isoformat()}")
    if order.promised_eta:
        print(f"Promised ETA: {order.promised_eta.isoformat()} (Delayed Promise: {order.delayed_promise})")

    print("Substitutions:")
    for item in order.line_items:
        if item.sku_id != item.fulfilled_sku_id:
            print(f"  {item.sku_id} -> {item.fulfilled_sku_id} (Qty: {item.fulfilled_quantity})")

    print(f"Delivery Fee: Rs {order.delivery_fee}")
    print(f"Batch ID: {order.batch_id}")

    if order.actual_delivery_time:
        print(f"Actual Delivery: {order.actual_delivery_time.isoformat()}")
        print(f"SLA Compensation: Rs {order.sla_compensation} (Coupon: {order.free_delivery_coupon})")
