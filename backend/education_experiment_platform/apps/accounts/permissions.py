from rest_framework.permissions import BasePermission

from .errors import PortalAccessDenied


class IsAuthenticatedAccount(BasePermission):
    def has_permission(self, request, view) -> bool:  # type: ignore[no-untyped-def]
        return bool(getattr(request, "user", None))


class PortalPermission(BasePermission):
    portal = ""

    def has_permission(self, request, view) -> bool:  # type: ignore[no-untyped-def]
        if getattr(request, "portal", "") != self.portal:
            raise PortalAccessDenied(detail={"required_portal": self.portal})
        return bool(getattr(request, "user", None))


class IsUserPortal(PortalPermission):
    portal = "USER"


class IsTeachingPortal(PortalPermission):
    portal = "TEACHING"


class IsPlatformPortal(PortalPermission):
    portal = "PLATFORM"
