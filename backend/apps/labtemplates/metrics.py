from prometheus_client import Counter, Gauge, Histogram

PRECHECK_RUNS = Counter(
    "labtemplate_precheck_runs_total",
    "Template precheck runs by result",
    ("result",),
)
PRECHECK_ACTIVE = Gauge(
    "labtemplate_precheck_active",
    "Template precheck runs currently active",
)
PRECHECK_DURATION = Histogram(
    "labtemplate_precheck_duration_seconds",
    "Template precheck duration",
)
ASSET_SCANS = Counter(
    "labtemplate_asset_scans_total",
    "Template asset scans by result",
    ("result",),
)
