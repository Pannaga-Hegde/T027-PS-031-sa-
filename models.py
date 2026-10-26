from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime, time

@dataclass
class SKU:
    id: str
    category: str
    brand: str
    price: float

@dataclass
class Store:
    id: str
    lat: float
    lon: float
    opening_time: time
    closing_time: time
    picking_capacity: int = 12
    active_riders: int = 0
    inventory: Dict[str, int] = field(default_factory=dict)
    weather_hold_until: Optional[datetime] = None
    picking_slots: Dict[str, int] = field(default_factory=dict) # To keep track of load

@dataclass
class LineItem:
    sku_id: str
    quantity: int
    original_price: float
    fulfilled_sku_id: Optional[str] = None
    fulfilled_quantity: int = 0
    final_price: float = 0.0

@dataclass
class Order:
    id: str
    customer_lat: float
    customer_lon: float
    timestamp: datetime
    line_items: List[LineItem]
    substitution_preference: str # ALLOW, SIMILAR_ONLY, NONE

    # State
    status: str = "PENDING"
    store_id: Optional[str] = None
    promised_eta: Optional[datetime] = None
    delayed_promise: bool = False
    delivery_fee: float = 0.0
    allocated_slot: Optional[datetime] = None
    batch_id: Optional[str] = None
    dispatch_time: Optional[datetime] = None
    actual_delivery_time: Optional[datetime] = None
    sla_compensation: float = 0.0
    free_delivery_coupon: bool = False

@dataclass
class Batch:
    id: str
    store_id: str
    orders: List[Order] = field(default_factory=list)
    rider_id: Optional[str] = None
    dispatch_time: Optional[datetime] = None

@dataclass
class Rider:
    id: str
    daily_penalties: float = 0.0
    daily_bonus: float = 0.0
