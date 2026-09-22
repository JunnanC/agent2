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
