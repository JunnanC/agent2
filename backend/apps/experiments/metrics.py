from prometheus_client import Counter, Histogram

PUBLICATION_DECISIONS_TOTAL = Counter(
    "experiment_publication_decisions_total",
    "Experiment publication outcomes",
    ("result",),
)
TASK_ASSIGNMENTS_TOTAL = Counter(
    "experiment_task_assignments_total",
    "Experiment task assignment outcomes",
    ("result",),
)
TASK_TRANSITIONS_TOTAL = Counter(
    "experiment_task_transitions_total",
    "Experiment task state transitions",
    ("from_status", "to_status"),
)
PUBLICATION_ASSIGNMENT_DURATION = Histogram(
    "experiment_publication_assignment_duration_seconds",
    "Experiment task assignment duration",
)
