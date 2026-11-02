from prometheus_client import Counter

INTEGRATION_RATE_LIMIT_REJECTIONS = Counter(
    "integration_rate_limit_rejections_total", "Rejected integration requests"
)
WEBHOOK_DELIVERIES_TOTAL = Counter(
    "webhook_deliveries_total", "Webhook delivery outcomes", ("result",)
)
WEBHOOK_ATTEMPTS_TOTAL = Counter(
    "webhook_delivery_attempts_total", "Webhook delivery attempts", ("result",)
)
