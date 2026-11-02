from prometheus_client import Counter, Gauge, Histogram

ANALYTICS_PROJECTION_RUNS = Counter(
    "analytics_projection_runs_total", "Analytics projection runs", ("kind", "result")
)
ANALYTICS_PROJECTION_LAG = Gauge(
    "analytics_projection_lag_seconds", "Age of the latest analytics projection", ("kind",)
)
RISK_SIGNALS_TOTAL = Counter(
    "course_risk_signals_total", "Risk signal generation and handling", ("kind", "result")
)
RESOURCE_COST_AMOUNT = Counter(
    "resource_cost_amount", "Projected resource cost", ("resource_type",)
)
ANALYTICS_DURATION = Histogram(
    "analytics_projection_duration_seconds", "Projection duration", ("kind",)
)
RUNTIME_LOG_QUERIES = Counter(
    "runtime_log_queries_total", "Runtime log queries by outcome", ("result",)
)
RUNTIME_LOG_HEALTH = Gauge(
    "runtime_log_backend_health", "Runtime log backend health (1 healthy, 0 unavailable)"
)
