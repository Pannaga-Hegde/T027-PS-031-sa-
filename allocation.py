import math
from typing import List, Optional, Tuple
from datetime import datetime
from models import Store, Order

def calculate_haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    # Earth radius in kilometers
    R = 6371.0

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2.0) ** 2

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    distance = R * c
    # Haversine distance rounded to 2 decimals
    return round(distance, 2)

def is_serviceable(store: Store, order: Order) -> Tuple[bool, Optional[str]]:
    # Distance check
    distance = calculate_haversine(store.lat, store.lon, order.customer_lat, order.customer_lon)
    if distance > 3.0:
        return False, "DISTANCE_EXCEEDED"

    # Store hours check
    order_time = order.timestamp.time()
    if not (store.opening_time <= order_time <= store.closing_time):
        return False, "OUTSIDE_HOURS"

    # Weather hold check
    if store.weather_hold_until and order.timestamp < store.weather_hold_until:
        return False, "WEATHER_HOLD"

    return True, None

def get_store_metrics(store: Store, order: Order) -> Tuple[bool, float, int, float]:
    # 1. 100% stock check
    # 2. Distance
    # 3. Load in current 10-min picking slot
    # 4. Line-fill percent if none has 100% stock

    total_lines = len(order.line_items)
    fulfilled_lines = 0

    for item in order.line_items:
        if store.inventory.get(item.sku_id, 0) >= item.quantity:
            fulfilled_lines += 1

    has_full_stock = (fulfilled_lines == total_lines)
    line_fill_percent = (fulfilled_lines / total_lines) * 100 if total_lines > 0 else 100.0

    distance = calculate_haversine(store.lat, store.lon, order.customer_lat, order.customer_lon)

    # Calculate current slot load
    # Slot is based on order timestamp aligned to 10 min boundaries
    minutes = order.timestamp.minute
    slot_minute = (minutes // 10) * 10
    slot_time = order.timestamp.replace(minute=slot_minute, second=0, microsecond=0)
    slot_key = slot_time.isoformat()

    current_load = store.picking_slots.get(slot_key, 0)

    return (has_full_stock, distance, current_load, line_fill_percent)

from datetime import timedelta

def allocate_picking_slot(store: Store, order_time: datetime) -> datetime:
    # Find the earliest slot that has capacity
    minutes = order_time.minute
    slot_minute = (minutes // 10) * 10
    current_slot = order_time.replace(minute=slot_minute, second=0, microsecond=0)

    while True:
        slot_key = current_slot.isoformat()
        current_load = store.picking_slots.get(slot_key, 0)

        if current_load < store.picking_capacity:
            store.picking_slots[slot_key] = current_load + 1
            return current_slot

        # Move to next 10-min slot
        current_slot += timedelta(minutes=10)

def calculate_eta(order: Order, store: Store, batch_sequence: int = 0) -> datetime:
    # 2 min pick + 1.5 min per km (rounded up) + 2 min per earlier drop
    distance = calculate_haversine(store.lat, store.lon, order.customer_lat, order.customer_lon)
    travel_time_minutes = math.ceil(1.5 * distance)

    total_minutes = 2 + travel_time_minutes + (2 * batch_sequence)

    # Calculate ETA based on picking slot allocation
    base_time = order.allocated_slot if order.allocated_slot else order.timestamp
    # But wait, if order rolled into next slot, ETA shifts +10 min
    # Wait, the rule says "when full the order rolls into the next slot and the ETA shifts +10 min"
    # Actually, the base time for calculating ETA should simply be the allocated slot or order timestamp?
    # Actually "starting from the order time" is 10-min slot. If it rolls over, ETA shifts +10 min for each rollover.
    # Let's say ETA = order.timestamp + picking delay + travel time + batch delays

    # If allocated_slot > order's initial slot, add the difference.
    minutes = order.timestamp.minute
    slot_minute = (minutes // 10) * 10
    initial_slot = order.timestamp.replace(minute=slot_minute, second=0, microsecond=0)

    if order.allocated_slot:
        slot_delay = (order.allocated_slot - initial_slot).total_seconds() / 60.0
    else:
        slot_delay = 0.0

    # Is weather hold applied? "orders already allocated there get their ETA extended by 10 min"
    # That happens dynamically during WEATHER_HOLD event.

    eta_minutes = total_minutes + slot_delay
    return order.timestamp + timedelta(minutes=eta_minutes)

def select_best_store(stores: List[Store], order: Order) -> Optional[Store]:
    serviceable_stores = []

    for store in stores:
        is_serv, reason = is_serviceable(store, order)
        if is_serv:
            metrics = get_store_metrics(store, order)
            serviceable_stores.append((store, metrics))

    if not serviceable_stores:
        return None

    # Sort criteria based on BR-02:
    # 1. 100% stock (True first) -> Sort by negation to have True first
    # 2. If none has 100% stock, highest line-fill percent
    # 3. Lowest distance
    # 4. Lowest load

    def sort_key(item):
        store, metrics = item
        has_full_stock, distance, current_load, line_fill_percent = metrics
        return (
            not has_full_stock,
            -line_fill_percent, # Prioritize line-fill when not 100% stock. Since it's 100% when full stock, it doesn't affect true full-stock comparisons.
            distance,
            current_load
        )

    serviceable_stores.sort(key=sort_key)

    best_store = serviceable_stores[0][0]
    return best_store
