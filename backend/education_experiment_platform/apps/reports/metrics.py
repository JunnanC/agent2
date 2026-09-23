from prometheus_client import Counter, Histogram

REPORT_SUBMISSIONS_TOTAL = Counter(
    "reports_submissions_total", "Report submissions by result", ["result"]
)
REPORT_ATTACHMENT_SCANS_TOTAL = Counter(
    "reports_attachment_scans_total", "Report attachment scans by result", ["result"]
)
REPORT_SUBMISSION_DURATION = Histogram(
    "reports_submission_duration_seconds", "Report submission transaction duration"
)
