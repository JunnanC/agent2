from prometheus_client import Counter, Histogram

WORKSPACE_SESSIONS_TOTAL = Counter(
    "workspace_sessions_total", "Workspace session decisions", ("action", "result")
)
WORKSPACE_AUTOSAVES_TOTAL = Counter(
    "workspace_autosaves_total", "Workspace autosave decisions", ("result",)
)
WORKSPACE_TICKET_DENIED_TOTAL = Counter(
    "workspace_ticket_denied_total", "Workspace ticket denials", ("reason",)
)
AUTOSAVE_CONFIRMED_LAG = Histogram(
    "autosave_confirmed_lag_seconds", "Time between client save and confirmation"
)
