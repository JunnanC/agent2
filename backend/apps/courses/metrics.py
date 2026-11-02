from prometheus_client import Counter

COURSE_ENROLLMENT_DECISIONS_TOTAL = Counter(
    "course_enrollment_decisions_total",
    "Course enrollment decisions by mode and result",
    ("mode", "result"),
)
COURSE_SCOPE_DENIED_TOTAL = Counter(
    "course_scope_denied_total",
    "Course scope denials by portal and resource type",
    ("portal", "resource"),
)
