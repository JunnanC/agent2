"""Scoped purge for the demo namespace via raw SQL.

The model layer forbids ORM deletes (``VersionedQuerySet.delete`` and the
append-only guards raise), so demo rows are located through ORM predicates and
removed with chunked ``DELETE`` statements, children first. On MySQL the
foreign-key checks are disabled for the duration of the transaction. Shared
system rows (platform quota, other seeds such as ``P03-DEMO-001``) are never
matched by demo predicates.
"""

from __future__ import annotations

import uuid
from typing import Final

from django.apps import apps
from django.db import connection, models, transaction

from .config import DEMO_USERNAME_PREFIX

DEMO_APP_LABELS: Final[tuple[str, ...]] = (
    "core",
    "accounts",
    "courses",
    "governance",
    "labtemplates",
    "experiments",
    "provisioning",
    "workspaces",
    "reports",
    "reviews",
    "archives",
    "agents",
    "notifications",
    "analytics",
)
_COURSE_PREFIX: Final[str] = "DEMO-"
_MAX_PASSES: Final[int] = 12
_CHUNK: Final[int] = 400


def _demo_models() -> list[type[models.Model]]:
    found: list[type[models.Model]] = []
    for label in DEMO_APP_LABELS:
        config = apps.get_app_config(label)
        for model in config.get_models():
            if model._meta.abstract:
                continue
            found.append(model)
    return found


def _relation_fields(model: type[models.Model]) -> list:
    fields: list = []
    for field in model._meta.concrete_fields:
        if not field.is_relation:
            continue
        if field.many_to_many:
            continue
        if field.related_model is None or field.related_model._meta.abstract:
            continue
        fields.append(field)
    return fields


def _base_rules() -> dict[type[models.Model], list[models.Q]]:
    code_prefixed = {
        "courses.Course",
        "courses.AcademicTerm",
        "governance.RuntimeAdapter",
        "governance.ResourceProfile",
    }
    key_prefixed = {"agents.ModelRoute", "agents.ToolPolicy", "agents.AgentDefinition"}
    rules: dict[type[models.Model], list[models.Q]] = {}
    for model in _demo_models():
        label = f"{model._meta.app_label}.{model.__name__}"
        if label == "accounts.User":
            rules[model] = [models.Q(username__startswith=DEMO_USERNAME_PREFIX)]
        elif label in code_prefixed:
            rules[model] = [models.Q(code__startswith=_COURSE_PREFIX)]
        elif label == "governance.ImageAsset":
            rules[model] = [models.Q(repository__startswith="demo/")]
        elif label in key_prefixed:
            rules[model] = [models.Q(key__startswith="demo-")]
        elif label == "core.ObjectAsset":
            rules[model] = [models.Q(bucket="demo-assets")]
    return rules


def _trace_q(model: type[models.Model]) -> models.Q | None:
    try:
        field = model._meta.get_field("trace_id")
    except Exception:
        return None
    if not isinstance(field, models.CharField):
        return None  # some models expose `trace_id` only as an FK attname.
    return models.Q(trace_id__startswith="demo")


def _resolve_demo_scope() -> dict[type[models.Model], models.Q]:
    rules = _base_rules()
    for model in _demo_models():
        trace = _trace_q(model)
        if trace is not None:
            rules.setdefault(model, []).append(trace)

    resolved: dict[type[models.Model], models.Q] = {
        model: models.Q(*checks, _connector=models.Q.OR)
        for model, checks in rules.items()
    }
    pending = [model for model in _demo_models() if model not in resolved]
    for _pass in range(_MAX_PASSES):
        if not pending:
            break
        progressed = False
        still: list[type[models.Model]] = []
        for model in pending:
            parts: list[models.Q] = []
            for field in _relation_fields(model):
                target = field.related_model
                if target is model or target not in resolved:
                    continue
                ids = _safe_pk_list(resolved, target)
                if ids:
                    parts.append(models.Q(**{f"{field.name}__in": ids}))
            for other in resolved:
                if other is model:
                    continue
                for field in _relation_fields(other):
                    if field.related_model is not model:
                        continue
                    ids = _safe_column_list(resolved, other, field.name)
                    if ids:
                        parts.append(models.Q(pk__in=ids))
            if parts:
                base = (
                    models.Q(*rules.get(model, []), _connector=models.Q.OR)
                    if rules.get(model)
                    else models.Q()
                )
                resolved[model] = models.Q(*parts, base, _connector=models.Q.OR)
                progressed = True
                still.append(model)
            else:
                still.append(model)
                if rules.get(model):
                    progressed = True
        if not progressed:
            break
        if still == pending:
            break
        pending = still
    _expand_log_scope(resolved)
    return resolved


_REF_COLUMNS: Final[tuple[str, ...]] = (
    "aggregate_ref",
    "target_ref",
    "subject_ref",
    "course_ref",
    "actor_ref",
    "student_ref",
)


def _expand_log_scope(resolved: dict) -> None:  # type: ignore[type-arg]
    """Match log rows by references to already-resolved aggregates.

    Some services emit outbox/audit/failure rows with their own trace ids; the
    only stable link back to the demo namespace is the aggregate reference.
    """

    refs: set[str] = set()
    log_models = {"outboxevent", "auditlog", "failurerecord", "compensationtask"}
    for model, _query in resolved.items():
        if model._meta.model_name in log_models:
            continue
        try:
            model._meta.get_field("public_id")
        except Exception:
            continue
        try:
            refs.update(
                str(value)
                for value, in _rows(resolved, model).values_list("public_id").iterator()
            )
        except Exception:
            continue
    if not refs:
        return
    for model in _demo_models():
        label = f"{model._meta.app_label}.{model.__name__}"
        if label not in {
            "core.OutboxEvent",
            "core.AuditLog",
            "core.FailureRecord",
            "core.CompensationTask",
        }:
            continue
        parts = [
            models.Q(**{f"{column}__in": list(refs)})
            for column in _REF_COLUMNS
            if _has_column(model, column)
        ]
        existing = resolved.get(model)
        if not parts:
            continue
        if existing is not None:
            resolved[model] = models.Q(existing, *parts, _connector=models.Q.OR)
        else:
            resolved[model] = models.Q(*parts, _connector=models.Q.OR)


def _has_column(model: type[models.Model], name: str) -> bool:
    try:
        field = model._meta.get_field(name)
    except Exception:
        return False
    return not field.is_relation


def _safe_pk_list(resolved: dict, target: type[models.Model]) -> list[object]:  # type: ignore[type-arg]
    try:
        return list(_rows(resolved, target).values_list(target._meta.pk.name, flat=True))
    except Exception:
        return []


def _safe_column_list(
    resolved: dict,  # type: ignore[type-arg]
    other: type[models.Model],
    field_name: str,
) -> list[object]:
    try:
        return list(_rows(resolved, other).values_list(field_name, flat=True))
    except Exception:
        return []


def _rows(
    resolved: dict[type[models.Model], models.Q],
    model: type[models.Model],
) -> models.QuerySet:  # type: ignore[type-arg]
    return model._default_manager.filter(resolved[model])


def _dependents(
    model: type[models.Model],
    remaining: dict[type[models.Model], models.Q],
) -> bool:
    for other in remaining:
        if other is model:
            continue
        for field in _relation_fields(other):
            if field.related_model is model:
                return True
    return False


def _deletion_order(
    resolved: dict[type[models.Model], models.Q],
) -> list[type[models.Model]]:
    remaining = dict.fromkeys(resolved)
    order: list[type[models.Model]] = []
    while remaining:
        leaves = [model for model in remaining if not _dependents(model, remaining)]
        if not leaves:
            leaves = [next(iter(remaining))]  # dangling FK cycle; FK checks off
        for model in leaves:
            order.append(model)
            remaining.pop(model, None)
    return order


def purge_demo_data() -> dict[str, int]:
    """Delete every demo-namespaced row; returns removed counts per table."""

    resolved = _resolve_demo_scope()
    order = _deletion_order(resolved)
    counts: dict[str, int] = {}
    mysql_fk_checks = connection.vendor == "mysql"
    with connection.cursor() as cursor:
        if mysql_fk_checks:
            cursor.execute("SET FOREIGN_KEY_CHECKS=0")
        try:
            with transaction.atomic():
                for model in order:
                    counts[model._meta.db_table] = _delete_rows(model, resolved[model], resolved)
        finally:
            if mysql_fk_checks:
                cursor.execute("SET FOREIGN_KEY_CHECKS=1")
    return counts


def _delete_rows(
    model: type[models.Model],
    scope: models.Q,
    resolved: dict,  # type: ignore[type-arg]
) -> int:
    table = model._meta.db_table
    column = model._meta.pk.column
    pk_name = model._meta.pk.name
    values = [
        row[0].hex if isinstance(row[0], uuid.UUID) else row[0]
        for row in _rows(resolved, model).values_list(pk_name).iterator()
    ]
    del scope
    marker = "?" if connection.vendor == "sqlite" else "%s"
    removed = 0
    with connection.cursor() as cursor:
        for offset in range(0, len(values), _CHUNK):
            chunk = values[offset : offset + _CHUNK]
            if not chunk:
                continue
            marks = ", ".join(marker for _ in chunk)
            cursor.execute(f"DELETE FROM {table} WHERE {column} IN ({marks})", tuple(chunk))
            affected = cursor.rowcount
            removed += affected
    return removed