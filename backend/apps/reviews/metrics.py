from prometheus_client import Counter

REVIEW_DECISIONS_TOTAL = Counter(
    "reviews_decisions_total", "Teacher review decisions", ("decision",)
)
AUTO_CHECK_RUNS_TOTAL = Counter(
    "reviews_auto_check_runs_total", "Review auto-check runs by result", ("result",)
)
SIMILARITY_RUNS_TOTAL = Counter(
    "reviews_similarity_runs_total", "Review similarity runs by result", ("result",)
)
