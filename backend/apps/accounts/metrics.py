from prometheus_client import Counter

PORTAL_LOGIN_TOTAL = Counter(
    "portal_login_total",
    "Portal login attempts by result",
    ("portal", "result"),
)
PORTAL_ACCESS_DENIED_TOTAL = Counter(
    "portal_access_denied_total",
    "Portal admission denials",
    ("portal", "reason"),
)
