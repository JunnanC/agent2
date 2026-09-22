from django.test import SimpleTestCase
from education_experiment_platform.middleware import IDEMPOTENCY_EXEMPT_POST_PATHS

from apps.core.pagination import PageSpec, PaginationError, decode_cursor, encode_cursor


class CoreUtilityTests(SimpleTestCase):
    def test_page_pagination_enforces_maximum_size(self) -> None:
        self.assertEqual(PageSpec.parse("2", "100").offset, 100)
        with self.assertRaises(PaginationError):
            PageSpec.parse(1, 101)

    def test_cursor_round_trip_is_url_safe(self) -> None:
        cursor = encode_cursor({"created_at": "2026-09-20T00:00:00Z", "id": 42})
        self.assertNotIn("=", cursor)
        self.assertEqual(decode_cursor(cursor)["id"], 42)

    def test_only_the_five_architecture_post_exceptions_are_exempt(self) -> None:
        self.assertEqual(
            IDEMPOTENCY_EXEMPT_POST_PATHS,
            {
                "/api/v2/auth/login",
                "/api/v2/auth/logout",
                "/api/v2/auth/logout-all",
                "/api/v2/integrations/oauth/token",
                "/api/v2/course-invitations/resolve",
            },
        )
