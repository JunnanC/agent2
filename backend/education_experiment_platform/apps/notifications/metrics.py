from prometheus_client import Counter

NOTIFICATIONS_TOTAL = Counter(
    "notifications_total", "Notifications created and read", ("kind", "result")
)
