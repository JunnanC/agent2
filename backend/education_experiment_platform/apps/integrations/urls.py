from django.urls import path

from .views import (
    OAuthTokenView,
    OIDCCallbackView,
    OIDCStartView,
    OpenCourseExperimentsView,
    OpenCourseProgressView,
    OpenCoursesView,
    PlatformAPIClientDetailView,
    PlatformAPIClientGrantView,
    PlatformAPIClientRotateView,
    PlatformAPIClientView,
    PlatformOIDCIdentityView,
    PlatformOIDCProviderDetailView,
    PlatformOIDCProviderRotateView,
    PlatformOIDCProviderView,
    PlatformWebhookAttemptView,
    PlatformWebhookDeliveryView,
    PlatformWebhookEndpointDetailView,
    PlatformWebhookEndpointView,
    PlatformWebhookRetryView,
    PlatformWebhookRotateView,
    UserOIDCIdentityView,
)

urlpatterns = [
    path("auth/oidc/<str:provider_key>/start", OIDCStartView.as_view()),
    path("auth/oidc/<str:provider_key>/callback", OIDCCallbackView.as_view()),
    path("me/oidc-identities", UserOIDCIdentityView.as_view()),
    path("me/oidc-identities/<str:identity_id>/unlink", UserOIDCIdentityView.as_view()),
    path("platform/integrations/oidc-providers", PlatformOIDCProviderView.as_view()),
    path(
        "platform/integrations/oidc-providers/<str:provider_id>",
        PlatformOIDCProviderDetailView.as_view(),
    ),
    path(
        "platform/integrations/oidc-providers/<str:provider_id>/rotate-secret",
        PlatformOIDCProviderRotateView.as_view(),
    ),
    path("platform/integrations/oidc-identities", PlatformOIDCIdentityView.as_view()),
    path(
        "platform/integrations/oidc-identities/<str:identity_id>/unlink",
        PlatformOIDCIdentityView.as_view(),
    ),
    path("platform/integrations/api-clients", PlatformAPIClientView.as_view()),
    path(
        "platform/integrations/api-clients/<str:client_id>", PlatformAPIClientDetailView.as_view()
    ),
    path(
        "platform/integrations/api-clients/<str:client_id>/rotate-secret",
        PlatformAPIClientRotateView.as_view(),
    ),
    path(
        "platform/integrations/api-clients/<str:client_id>/grants",
        PlatformAPIClientGrantView.as_view(),
    ),
    path("platform/integrations/webhook-endpoints", PlatformWebhookEndpointView.as_view()),
    path(
        "platform/integrations/webhook-endpoints/<str:endpoint_id>",
        PlatformWebhookEndpointDetailView.as_view(),
    ),
    path(
        "platform/integrations/webhook-endpoints/<str:endpoint_id>/rotate-secret",
        PlatformWebhookRotateView.as_view(),
    ),
    path("platform/integrations/webhook-deliveries", PlatformWebhookDeliveryView.as_view()),
    path(
        "platform/integrations/webhook-deliveries/<str:delivery_id>/attempts",
        PlatformWebhookAttemptView.as_view(),
    ),
    path(
        "platform/integrations/webhook-deliveries/<str:delivery_id>/retry",
        PlatformWebhookRetryView.as_view(),
    ),
    path("integrations/oauth/token", OAuthTokenView.as_view()),
    path("integrations/open/courses", OpenCoursesView.as_view()),
    path(
        "integrations/open/courses/<str:course_id>/experiments", OpenCourseExperimentsView.as_view()
    ),
    path("integrations/open/courses/<str:course_id>/progress", OpenCourseProgressView.as_view()),
]
