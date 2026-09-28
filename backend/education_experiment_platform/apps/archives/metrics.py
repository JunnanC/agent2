from prometheus_client import Counter, Gauge, Histogram

ARCHIVE_JOBS_TOTAL = Counter(
    "archive_jobs_total", "Archive jobs by result", ("result", "terminal_target")
)
ARCHIVE_DURATION_SECONDS = Histogram(
    "archive_duration_seconds", "Time spent producing and verifying an archive"
)
ARCHIVE_RECOVERY_TOTAL = Counter(
    "archive_recovery_total", "Archive and runtime recovery operations", ("operation", "result")
)
ARCHIVE_EXPORTS_TOTAL = Counter(
    "archive_exports_total", "Archive export grants", ("portal", "result")
)
ARCHIVE_RETENTION_TOTAL = Counter(
    "archive_retention_total", "Archive retention cleanup outcomes", ("result",)
)
RUNTIME_RECONCILIATION_ISSUES = Gauge(
    "runtime_reconciliation_issues",
    "Current runtime reconciliation issues",
    ("kind",),
)
