from prometheus_client import Counter, Histogram

PROVISIONING_JOBS_TOTAL = Counter(
    "provisioning_jobs_total",
    "Provisioning job outcomes",
    ("status", "runtime_type"),
)
PROVISIONING_STAGE_TOTAL = Counter(
    "provisioning_stage_events_total",
    "Provisioning stage outcomes",
    ("stage", "status"),
)
PROVISIONING_DURATION = Histogram(
    "provisioning_duration_seconds",
    "Provisioning duration by runtime type",
    ("runtime_type",),
)
