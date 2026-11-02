from django.urls import path

from .views import NotificationDetailView, NotificationListView, NotificationPreferenceView

urlpatterns = [
    path("notifications", NotificationListView.as_view()),
    path("notifications/<str:notification_id>/read", NotificationDetailView.as_view()),
    path("notification-preferences", NotificationPreferenceView.as_view()),
]
