import json
import logging
from typing import List, Dict, Any
from datetime import datetime, timedelta

class CommandProcessor:
    def __init__(self):
        self.current_time = None

    def process_command_file(self, filepath: str):
        try:
            with open(filepath, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        cmd = json.loads(line)
                        self._handle_command(cmd)
                    except json.JSONDecodeError:
                        logging.error(f"Invalid JSON at line {line_num}: {line}")
                    except Exception as e:
                        logging.error(f"Error processing command at line {line_num}: {e}")
        except FileNotFoundError:
            logging.error(f"Command file not found: {filepath}")

    def _handle_command(self, cmd: Dict[str, Any]):
        cmd_type = cmd.get("type")
        if not cmd_type:
            return

        # Update clock if timestamp is present
        if "timestamp" in cmd:
            cmd_time = datetime.fromisoformat(cmd["timestamp"])
            if self.current_time is None or cmd_time > self.current_time:
                # Advance time and trigger any time-based events
                if hasattr(self, 'advance_time'):
                    self.advance_time(cmd_time)
                else:
                    self.current_time = cmd_time

        handler = getattr(self, f"handle_{cmd_type.lower()}", None)
        if handler:
            handler(cmd)
        else:
            logging.warning(f"Unknown command type: {cmd_type}")

    # Skeleton handlers
    def handle_init_store(self, cmd: Dict[str, Any]):
        pass

    def handle_add_inventory(self, cmd: Dict[str, Any]):
        pass

    def handle_place_order(self, cmd: Dict[str, Any]):
        pass

    def handle_weather_hold(self, cmd: Dict[str, Any]):
        store_id = cmd["store_id"]
        timestamp = datetime.fromisoformat(cmd["timestamp"])

        store = self.stores.get(store_id)
        if store:
            store.weather_hold_until = timestamp + timedelta(minutes=20)

            # orders already allocated there get their ETA extended by 10 min
            for order in self.orders.values():
                if order.store_id == store_id and order.status in ["ALLOCATED", "PICKING"]:
                    if order.promised_eta:
                        order.promised_eta += timedelta(minutes=10)

    def handle_deliver_order(self, cmd: Dict[str, Any]):
        pass

    def handle_cancel_order(self, cmd: Dict[str, Any]):
        order_id = cmd["order_id"]
        order = self.orders.get(order_id)
        if not order:
            return

        # Determine actual status right now based on time
        if order.status == "ALLOCATED":
            base_time = order.allocated_slot if order.allocated_slot else order.timestamp
            if self.current_time and self.current_time >= base_time:
                order.status = "PICKING"

        if order.status == "PENDING" or order.status == "ALLOCATED":
            # Before picking starts
            order.status = "CANCELLED"
            order.refund_amount = self._calculate_original_value(order)
            order.cancellation_fee = 0.0
        elif order.status == "PICKING":
            # After picking starts and before dispatch costs Rs 20
            order.status = "CANCELLED"
            order.refund_amount = self._calculate_original_value(order) - 20.0
            order.cancellation_fee = 20.0
        elif order.status == "DISPATCHED" or order.status == "DELIVERED":
            # after dispatch no refund except for lines that were substituted without ALLOW
            order.status = "CANCELLED"
            refund = 0.0
            for item in order.line_items:
                if item.fulfilled_sku_id != item.sku_id and order.substitution_preference != "ALLOW":
                    refund += item.final_price
            order.refund_amount = refund
            order.cancellation_fee = 0.0 # Rest is not refunded, but fee is technically just not refunding

        # Remove from batch if it was active
        if order.batch_id and hasattr(self, 'active_batches'):
            for batch in self.active_batches:
                if batch.id == order.batch_id:
                    batch.orders = [o for o in batch.orders if o.id != order.id]

    def _calculate_original_value(self, order):
        return sum(self.skus[item.sku_id].price * item.quantity for item in order.line_items)

    def handle_print_trace(self, cmd: Dict[str, Any]):
        pass
