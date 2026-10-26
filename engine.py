import sys
import json
import logging
from datetime import datetime, timedelta, time
from typing import Dict, Any, List

from models import Order, Rider, Batch, Store, SKU, LineItem
from allocation import select_best_store, allocate_picking_slot, calculate_eta
from fulfillment import process_substitutions, evaluate_partial_fulfillment, calculate_delivery_fee
from batching import assign_to_batch, check_batch_dispatch
from processor import CommandProcessor

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

class EngineProcessor(CommandProcessor):
    def __init__(self):
        super().__init__()
        self.stores: Dict[str, Store] = {}
        self.orders: Dict[str, Order] = {}
        self.skus: Dict[str, SKU] = {}
        self.riders: Dict[str, Rider] = {}
        self.active_batches: List[Batch] = []
        self.batch_id_counter = 1

    def advance_time(self, new_time: datetime):
        # We need to simulate time passing from self.current_time up to new_time
        # Since we only have dispatch timeouts right now, we can just check if any batches
        # should dispatch. We should ideally advance minute-by-minute, but for batches,
        # we just check if dispatch timeout is <= new_time.

        self.current_time = new_time

        # Update states to PICKING if picking has started
        for order in self.orders.values():
            if order.status == "ALLOCATED":
                base_time = order.allocated_slot if order.allocated_slot else order.timestamp
                if self.current_time >= base_time:
                    order.status = "PICKING"

        batches_to_dispatch = []
        for batch in self.active_batches:
            if check_batch_dispatch(batch, self.current_time):
                batches_to_dispatch.append(batch)

        for batch in batches_to_dispatch:
            # The dispatch time should be exactly when it timed out, not new_time
            # check_batch_dispatch logic says: pick_time + 3 min.
            first_order = batch.orders[0]
            base_time = first_order.allocated_slot if first_order.allocated_slot else first_order.timestamp
            dispatch_timeout = base_time + timedelta(minutes=5) # 2 min pick + 3 min wait

            # Use max(dispatch_timeout, last_order_time)
            # Actually, just use dispatch_timeout if it's <= current_time
            self._dispatch_batch(batch, dispatch_timeout)

    def _generate_batch_id(self):
        bid = f"B{self.batch_id_counter:03d}"
        self.batch_id_counter += 1
        return bid

    def handle_init_store(self, cmd: Dict[str, Any]):
        try:
            opening = datetime.strptime(cmd.get("opening_time", "00:00"), "%H:%M").time()
            closing = datetime.strptime(cmd.get("closing_time", "23:59"), "%H:%M").time()
        except ValueError:
            opening = time(0, 0)
            closing = time(23, 59)

        store = Store(
            id=cmd["store_id"],
            lat=cmd["lat"],
            lon=cmd["lon"],
            opening_time=opening,
            closing_time=closing,
            picking_capacity=cmd.get("picking_capacity", 12),
            active_riders=cmd.get("active_riders", 0)
        )
        self.stores[store.id] = store

    def handle_add_inventory(self, cmd: Dict[str, Any]):
        store_id = cmd["store_id"]
        sku = SKU(
            id=cmd["sku_id"],
            category=cmd["category"],
            brand=cmd["brand"],
            price=float(cmd["price"])
        )
        self.skus[sku.id] = sku
        if store_id in self.stores:
            self.stores[store_id].inventory[sku.id] = cmd["quantity"]

    def handle_place_order(self, cmd: Dict[str, Any]):
        order_time = datetime.fromisoformat(cmd["timestamp"])

        line_items = []
        for li in cmd["line_items"]:
            # Basic validation
            sku = self.skus.get(li["sku_id"])
            price = sku.price if sku else 0.0
            line_items.append(LineItem(
                sku_id=li["sku_id"],
                quantity=li["quantity"],
                original_price=price
            ))

        order = Order(
            id=cmd["order_id"],
            customer_lat=cmd["customer_lat"],
            customer_lon=cmd["customer_lon"],
            timestamp=order_time,
            line_items=line_items,
            substitution_preference=cmd.get("substitution_preference", "NONE")
        )

        self.orders[order.id] = order

        # 1. Store Choice
        store = select_best_store(list(self.stores.values()), order)
        if not store:
            order.status = "REJECTED"
            return

        order.store_id = store.id

        # 2. Allocate Picking Slot
        order.allocated_slot = allocate_picking_slot(store, order.timestamp)
        order.status = "ALLOCATED"

        # 3. Fulfillment & Substitutions
        process_substitutions(order, store, self.skus)

        # 4. Partial Fulfillment Check
        if not evaluate_partial_fulfillment(order, self.skus):
            # It was cancelled, restore inventory
            for item in order.line_items:
                if item.fulfilled_quantity > 0 and item.fulfilled_sku_id:
                    store.inventory[item.fulfilled_sku_id] = store.inventory.get(item.fulfilled_sku_id, 0) + item.fulfilled_quantity
            return

        # 5. Delivery Fee
        calculate_delivery_fee(order, store)

        # 6. ETA Calculation (Baseline)
        order.promised_eta = calculate_eta(order, store, 0)

        # 7. Batching
        batch = assign_to_batch(order, self.active_batches, order.timestamp, self._generate_batch_id)

        # Re-calculate ETA if batched sequence > 0
        seq = len(batch.orders) - 1
        if seq > 0:
            order.promised_eta = calculate_eta(order, store, seq)

        # Check DELAYED_PROMISE flag *after* batching affects ETA
        if (order.promised_eta - order.timestamp).total_seconds() > 10 * 60:
            order.delayed_promise = True

        # Check if batch should dispatch
        if check_batch_dispatch(batch, order.timestamp):
            self._dispatch_batch(batch, order.timestamp)

    def _dispatch_batch(self, batch: Batch, current_time: datetime):
        batch.dispatch_time = current_time
        # Assign a rider
        store = self.stores.get(batch.store_id)
        if store and store.active_riders > 0:
            store.active_riders -= 1

        # Create a dummy rider if none registered (assuming for tests)
        rider_id = f"R_{batch.id}"
        if rider_id not in self.riders:
            self.riders[rider_id] = Rider(id=rider_id)
        batch.rider_id = rider_id

        for order in batch.orders:
            order.status = "DISPATCHED"
            order.dispatch_time = current_time

        if batch in self.active_batches:
            self.active_batches.remove(batch)

    def handle_deliver_order(self, cmd: Dict[str, Any]):
        order_id = cmd["order_id"]
        actual_time = datetime.fromisoformat(cmd["timestamp"])

        order = self.orders.get(order_id)
        if not order:
            return

        order.status = "DELIVERED"
        order.actual_delivery_time = actual_time

        # Calculate SLA compensation
        from engine_utils import calculate_sla_compensation, calculate_rider_penalty
        calculate_sla_compensation(order, actual_time)

        # Accumulate deliveries for the batch
        if order.batch_id:
            # We need to find the batch and see if all orders are delivered.
            # But the batch might have been removed from active_batches.
            # So we rely on checking all orders in the batch.
            batch_orders = [o for o in self.orders.values() if o.batch_id == order.batch_id]
            all_delivered = all(o.status == "DELIVERED" for o in batch_orders)

            if all_delivered:
                rider_id = f"R_{order.batch_id}"
                rider = self.riders.get(rider_id)
                if rider:
                    deliveries = [(o, o.actual_delivery_time) for o in batch_orders]
                    calculate_rider_penalty(rider, None, deliveries)

    def handle_print_trace(self, cmd: Dict[str, Any]):
        order_id = cmd["order_id"]
        order = self.orders.get(order_id)
        if order:
            from engine_utils import print_order_trace
            print_order_trace(order, self)
        else:
            print(f"Order {order_id} not found.")

def main():
    if len(sys.argv) < 2:
        print("Usage: python engine.py <command_file.jsonl>")
        sys.exit(1)

    command_file = sys.argv[1]

    processor = EngineProcessor()
    processor.process_command_file(command_file)

if __name__ == "__main__":
    main()
