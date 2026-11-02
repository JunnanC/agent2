from __future__ import annotations

from typing import cast

from django.test import SimpleTestCase, override_settings
from redis import Redis

from apps.accounts.errors import RateLimited
from apps.accounts.security import check_login_rate_limit, clear_login_rate_limit


class FakePipeline:
    def __init__(self, values: dict[str, int]) -> None:
        self.values = values
        self.key = ""

    def incr(self, key: str) -> FakePipeline:
        self.key = key
        return self

    def expire(self, key: str, _seconds: int) -> FakePipeline:
        if key != self.key:
            raise AssertionError("expiry key must match increment key")
        return self

    def execute(self) -> list[int | bool]:
        self.values[self.key] = self.values.get(self.key, 0) + 1
        return [self.values[self.key], True]


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}

    def pipeline(self, *, transaction: bool) -> FakePipeline:
        if not transaction:
            raise AssertionError("rate limit update must be transactional")
        return FakePipeline(self.values)

    def delete(self, key: str) -> int:
        return int(self.values.pop(key, None) is not None)


class LoginRateLimitTests(SimpleTestCase):
    @override_settings(LOGIN_RATE_LIMIT_ATTEMPTS=2, LOGIN_RATE_LIMIT_WINDOW_SECONDS=300)
    def test_rate_limit_is_scoped_by_portal_ip_and_normalized_account(self) -> None:
        fake = FakeRedis()
        client = cast(Redis, fake)

        first_key = check_login_rate_limit(
            identifier=" User@Example.edu ", ip_address="192.0.2.10", portal="USER", client=client
        )
        second_key = check_login_rate_limit(
            identifier="user@example.edu", ip_address="192.0.2.10", portal="USER", client=client
        )
        self.assertEqual(first_key, second_key)
        with self.assertRaises(RateLimited):
            check_login_rate_limit(
                identifier="user@example.edu",
                ip_address="192.0.2.10",
                portal="USER",
                client=client,
            )

        other_ip_key = check_login_rate_limit(
            identifier="user@example.edu", ip_address="192.0.2.11", portal="USER", client=client
        )
        other_account_key = check_login_rate_limit(
            identifier="other@example.edu", ip_address="192.0.2.10", portal="USER", client=client
        )
        other_portal_key = check_login_rate_limit(
            identifier="user@example.edu",
            ip_address="192.0.2.10",
            portal="TEACHING",
            client=client,
        )
        self.assertEqual(len({first_key, other_ip_key, other_account_key, other_portal_key}), 4)

        clear_login_rate_limit(first_key, client=client)
        check_login_rate_limit(
            identifier="user@example.edu", ip_address="192.0.2.10", portal="USER", client=client
        )
