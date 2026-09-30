from drf_spectacular.extensions import OpenApiAuthenticationExtension


class IntegrationBearerAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "apps.integrations.authentication.IntegrationTokenAuthentication"
    name = "IntegrationBearerAuth"

    def get_security_definition(self, auto_schema):  # type: ignore[no-untyped-def]
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "integration access token",
        }
