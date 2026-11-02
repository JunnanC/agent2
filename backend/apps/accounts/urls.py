from django.urls import path

from .views import (
    AdminAssignmentDetailView,
    AdminAssignmentsView,
    CsrfView,
    GrantAdminAssignmentView,
    GrantTeacherQualificationView,
    LoginView,
    LogoutAllView,
    LogoutView,
    MeView,
    MyVerificationView,
    PasswordView,
    PlatformRevokeSessionsView,
    PlatformUserDetailView,
    PlatformUsersView,
    ReviewVerificationView,
    SessionStepUpView,
    TeacherQualificationDetailView,
    TeacherQualificationsView,
    VerificationsView,
)

urlpatterns = [
    path("auth/csrf", CsrfView.as_view(), name="auth-csrf"),
    path("auth/login", LoginView.as_view(), name="auth-login"),
    path("auth/logout", LogoutView.as_view(), name="auth-logout"),
    path("auth/logout-all", LogoutAllView.as_view(), name="auth-logout-all"),
    path("auth/session/step-up", SessionStepUpView.as_view(), name="auth-session-step-up"),
    path("me", MeView.as_view(), name="me"),
    path("me/password", PasswordView.as_view(), name="me-password"),
    path("me/verification", MyVerificationView.as_view(), name="me-verification"),
    path("platform/users", PlatformUsersView.as_view(), name="platform-users"),
    path(
        "platform/users/<str:user_id>",
        PlatformUserDetailView.as_view(),
        name="platform-user-detail",
    ),
    path(
        "platform/users/<str:user_id>/revoke-sessions",
        PlatformRevokeSessionsView.as_view(),
        name="platform-user-revoke-sessions",
    ),
    path(
        "platform/teacher-qualifications",
        TeacherQualificationsView.as_view(),
        name="platform-teacher-qualifications",
    ),
    path(
        "platform/users/<str:user_id>/teacher-qualification",
        GrantTeacherQualificationView.as_view(),
        name="platform-grant-teacher-qualification",
    ),
    path(
        "platform/teacher-qualifications/<str:qualification_id>",
        TeacherQualificationDetailView.as_view(),
        name="platform-teacher-qualification-detail",
    ),
    path(
        "platform/admin-assignments",
        AdminAssignmentsView.as_view(),
        name="platform-admin-assignments",
    ),
    path(
        "platform/users/<str:user_id>/admin-assignment",
        GrantAdminAssignmentView.as_view(),
        name="platform-grant-admin-assignment",
    ),
    path(
        "platform/admin-assignments/<str:assignment_id>",
        AdminAssignmentDetailView.as_view(),
        name="platform-admin-assignment-detail",
    ),
    path(
        "platform/verifications",
        VerificationsView.as_view(),
        name="platform-verifications",
    ),
    path(
        "platform/verifications/<str:verification_id>/review",
        ReviewVerificationView.as_view(),
        name="platform-verification-review",
    ),
]
