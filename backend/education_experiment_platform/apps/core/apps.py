from django.apps import AppConfig
from django.db.backends.signals import connection_created


def _register_sqlite_ascii_bin(*, connection, **_kwargs: object) -> None:  # type: ignore[no-untyped-def]
    if connection.vendor != "sqlite" or connection.connection is None:
        return

    def compare(left: str, right: str) -> int:
        return (left > right) - (left < right)

    connection.connection.create_collation("ascii_bin", compare)


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"

    def ready(self) -> None:
        connection_created.connect(
            _register_sqlite_ascii_bin,
            dispatch_uid="core.register_sqlite_ascii_bin",
        )
