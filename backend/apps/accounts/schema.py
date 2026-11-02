from drf_spectacular.extensions import OpenApiAuthenticationExtension


class PortalSessionAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "apps.accounts.authentication.PortalSessionAuthentication"
    name = "portalSession"

    def get_security_definition(self, auto_schema) -> dict[str, str]:  # type: ignore[no-untyped-def]
        return {"type": "apiKey", "in": "cookie", "name": "sessionid"}
