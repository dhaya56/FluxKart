"""
Custom Prometheus Metrics for FluxKart.

WHY CUSTOM METRICS OVER DEFAULT:
──────────────────────────────────
The prometheus-fastapi-instrumentator already gives us:
  - Request count per endpoint
  - Request latency per endpoint
  - Response status codes

But for a flash sale system, we need BUSINESS metrics:
  - How many reservations succeeded vs failed?
  - How much inventory is remaining per sale?
  - How deep is the waiting queue?
  - How many reservations expired?

These tell us if the BUSINESS is working, not just the API.
This is what separates a production system from a student project.

METRIC TYPES USED:
───────────────────
Counter   → only goes up (total reservations, total failures)
Gauge     → can go up or down (current inventory, queue depth)
Histogram → measures distribution (reservation latency buckets)
"""

from prometheus_client import Counter, Gauge, Histogram

# ── Reservation Metrics ───────────────────────────────────────────────────────

RESERVATION_ATTEMPTS = Counter(
    "fluxkart_reservation_attempts_total",
    "Total number of reservation attempts",
    ["status"],  # Labels: success, failed_no_inventory, failed_invalid_sale, duplicate
)

RESERVATION_LATENCY = Histogram(
    "fluxkart_reservation_duration_seconds",
    "Time taken to process a reservation request",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0],
)

RESERVATIONS_EXPIRED = Counter(
    "fluxkart_reservations_expired_total",
    "Total number of reservations that expired without payment",
)

# ── Inventory Metrics ─────────────────────────────────────────────────────────

INVENTORY_REMAINING = Gauge(
    "fluxkart_inventory_remaining",
    "Current available inventory per sale",
    ["sale_id"],  # Label: one gauge per active sale
)

INVENTORY_RELEASES = Counter(
    "fluxkart_inventory_releases_total",
    "Total inventory units released back due to expired reservations",
)

# ── Queue Metrics ─────────────────────────────────────────────────────────────

QUEUE_DEPTH = Gauge(
    "fluxkart_queue_depth",
    "Current number of users in waiting queue per sale",
    ["sale_id"],
)

# ── Order Metrics ─────────────────────────────────────────────────────────────

ORDERS_CREATED = Counter(
    "fluxkart_orders_created_total",
    "Total number of orders successfully created",
)

ORDERS_FAILED = Counter(
    "fluxkart_orders_failed_total",
    "Total number of orders that failed processing",
)

# ── Rate Limit Metrics ────────────────────────────────────────────────────────

RATE_LIMIT_HITS = Counter(
    "fluxkart_rate_limit_hits_total",
    "Total number of requests rejected by rate limiter",
    ["path"],
)