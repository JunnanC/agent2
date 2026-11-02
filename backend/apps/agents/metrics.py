from prometheus_client import Counter, Histogram

AGENT_TOOL_CALLS_TOTAL = Counter(
    "agent_tool_calls_total", "Agent tool calls by risk and result", ("risk", "result")
)
AGENT_ANSWERS_TOTAL = Counter(
    "agent_answers_total",
    "Agent answers by mode and citation status",
    ("mode", "citation_status", "result"),
)
AGENT_EVAL_SCORE = Histogram(
    "agent_eval_score", "Agent evaluation score by suite and dimension", ("suite", "dimension")
)
AGENT_LATENCY_SECONDS = Histogram("agent_latency_seconds", "Agent gateway latency")
