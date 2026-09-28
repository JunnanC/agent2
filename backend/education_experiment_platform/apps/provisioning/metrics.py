from prometheus_client import Counter, Gauge, Histogram

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

# Task/container identifiers stay in structured logs; metric labels remain bounded.
RUNTIME_CONTAINER_CREATE_DURATION = Histogram(
    "runtime_container_create_duration_seconds",
    "Managed runtime container creation duration",
    ("driver", "result"),
)
RUNTIME_WORKSPACE_START_DURATION = Histogram(
    "runtime_workspace_start_duration_seconds",
    "Managed workspace startup duration",
    ("driver", "result"),
)
RUNTIME_ENGINE_UNAVAILABLE_TOTAL = Counter(
    "runtime_engine_unavailable_total",
    "Runtime engine unavailable or unreachable outcomes",
    ("driver",),
)
RUNTIME_ENGINE_HEALTH = Gauge(
    "runtime_engine_health",
    "Runtime engine health (1 healthy, 0 unavailable)",
    ("driver",),
)
RUNTIME_INVENTORY = Gauge(
    "runtime_inventory",
    "Managed runtime inventory by driver, kind and status",
    ("driver", "kind", "status"),
)
RUNTIME_ORPHAN_RESOURCES = Gauge(
    "runtime_orphan_resources",
    "Runtime resources without a matching database fact",
    ("kind",),
)
RUNTIME_EXECUTION_RESULTS = Counter(
    "runtime_execution_results_total",
    "Student runtime execution outcomes",
    ("driver", "status"),
)
RUNTIME_EXECUTION_DURATION = Histogram(
    "runtime_execution_duration_seconds",
    "Student runtime execution duration",
    ("driver",),
)
RUNTIME_JUDGE_EXECUTIONS = Counter(
    "runtime_judge_executions_total",
    "Teacher judge execution outcomes",
    ("driver", "status"),
)
RUNTIME_JUDGE_EXECUTION_DURATION = Histogram(
    "runtime_judge_execution_duration_seconds",
    "Teacher judge execution duration",
    ("driver",),
)

ENGINE_UNAVAILABLE_CODES = frozenset(
    {
        "RUNTIME_UNAVAILABLE",
        "RUNTIME_CLIENT_UNAVAILABLE",
        "RUNTIME_SERVICE_QUERY_FAILED",
        "RUNTIME_STATUS_FAILED",
        "RUNTIME_EXECUTION_UNAVAILABLE",
    }
)


def is_engine_unavailable(error_code: str) -> bool:
    return error_code in ENGINE_UNAVAILABLE_CODES
