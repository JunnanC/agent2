from prometheus_client import Counter, Gauge

QUOTA_RESERVED = Gauge(
    "quota_reserved",
    "Active governance quota reservations by dimension",
    ("dimension",),
)
GOVERNANCE_ALERTS = Gauge(
    "governance_alerts",
    "Governance alert summaries by severity",
    ("severity",),
)
QUOTA_OPERATIONS = Counter(
    "governance_quota_operations_total",
    "Quota reservation operations by result",
    ("operation", "result"),
)
RUNTIME_ADAPTER_HEALTH = Gauge(
    "governance_runtime_adapter_health",
    "Runtime adapter health (1 for current state)",
    ("adapter", "status"),
)
RUNTIME_ADAPTER_CAPACITY = Gauge(
    "governance_runtime_adapter_capacity",
    "Runtime adapter capacity by resource and kind",
    ("adapter", "resource", "kind"),
)
