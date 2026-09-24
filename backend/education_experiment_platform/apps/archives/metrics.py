from prometheus_client import Counter, Histogram

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
