# Design Document: Dark-Store Order Allocation Engine

## Business Rules

*   **BR-01 (Serviceability):** A store can serve an order only if straight-line distance <= 3.0 km and the order time is inside store hours; distance uses the haversine formula rounded to 2 decimals.
*   **BR-02 (Store Choice):** Among serviceable stores pick the one with 100% stock first; tie-break by lowest distance, then by lowest load in the current 10-min picking slot; if none has 100% stock pick highest line-fill percent.
*   **BR-03 (Picking Capacity):** Each store accepts at most its capacity (default 12 orders) per 10-min slot starting from the order time; when full the order rolls into the next slot and the ETA shifts +10 min.
*   **BR-04 (ETA):** Promised ETA = 2 min pick + 1.5 min per km (rounded up to the minute) + 2 min per earlier drop in the same batch; if ETA > 10 min and the customer did not opt into slow delivery, the order is tagged DELAYED_PROMISE and SLA compensation is pre-armed.
*   **BR-05 (Substitution):** When a line is short, ALLOW permits any SKU in the same category with price within +15% (customer pays original price); SIMILAR_ONLY permits only the same brand; NONE converts the shortfall into a partial line; a substituted line never costs more than the original.
*   **BR-06 (Partial Fulfillment):** If the fulfilled value drops below 60% of the original order value, the order is cancelled before dispatch with a full refund and no delivery fee. (Evaluated after substitution but before fee calculation because fees depend on final value and substitution affects the final value).
*   **BR-07 (Delivery Fee):** Rs 0 for order value >= Rs 199 after substitutions, else Rs 25; surge +Rs 15 when a store's active riders < 3 at allocation time; fee is frozen at allocation and never recomputed.
*   **BR-08 (Batching):** A rider may carry up to 3 orders whose drop points are within 1.0 km of each other and whose baseline promised ETAs differ by at most 4 min; a batch dispatches when full or 3 min after its first order was picked, whichever is earlier.
*   **BR-09 (SLA Compensation):** Actual delivery later than promised ETA by 5–10 min credits Rs 25 to the wallet; by more than 10 min credits Rs 50 plus a free delivery coupon; no compensation when the order carried DELAYED_PROMISE and the delay is within 5 min of the longer promise.
*   **BR-10 (Rider Penalty):** A rider who is late on 2 or more orders in a batch loses the Rs 20 batch bonus; a rider late on an order by more than 15 min gets a Rs 30 deduction, capped at Rs 90 per day.
*   **BR-11 (Weather Hold):** A WEATHER_HOLD command for a store stops new allocations for 20 min; orders already allocated there get their ETA extended by 10 min without compensation.
*   **BR-12 (Cancellation):** Customer cancellation before picking starts is free; after picking starts and before dispatch costs Rs 20; after dispatch no refund except for lines that were substituted without ALLOW.

## Explanation of Partial-Fulfillment Evaluation
Partial-fulfilment cancellation is evaluated after substitution because substitution may recover some order value, potentially keeping it above the 60% threshold. It is evaluated before fee calculation because if the order is cancelled, no delivery fee should be charged or computed, and if it is not cancelled, the delivery fee (e.g., free delivery over Rs 199) must be based on the final fulfilled value after substitutions.
