from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView

from .events import EventStreamView
from .health import HealthView, ReadinessView

urlpatterns = [
    path("", include("apps.accounts.urls")),
    path("", include("apps.governance.urls")),
    path("", include("apps.labtemplates.urls")),
    path("", include("apps.reviews.urls")),
    path("", include("apps.courses.urls")),
    path("health", HealthView.as_view(), name="health"),
    path("health/ready", ReadinessView.as_view(), name="readiness"),
    path("events/stream", EventStreamView.as_view(), name="event-stream"),
    path("schema", SpectacularAPIView.as_view(), name="openapi-schema"),
]
