import json
import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import cast

from apps.accounts.authentication import PortalSessionAuthentication
from apps.accounts.models import User
from apps.accounts.permissions import IsAuthenticatedAccount
from apps.core.models import OutboxEvent
from apps.courses.models import Course, CourseStaffGrant, Enrollment
from apps.courses.selectors import has_course_capability
from apps.experiments.models import ExperimentTask
from django.conf import settings
from django.http import StreamingHttpResponse
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import OpenApiResponse, extend_schema
from redis import Redis
from rest_framework.request import Request
from rest_framework.views import APIView


def _event_id(item: OutboxEvent) -> str:
    return f"{item.created_at.isoformat()}|{item.id}"


def _cursor_time(value: str) -> datetime | None:
    if not value or "|" not in value:
        return None
    return parse_datetime(value.split("|", 1)[0])


def _cursor_exists(value: str) -> bool:
    try:
        event_id = uuid.UUID(value.split("|", 1)[1])
    except (ValueError, IndexError):
        return False
    return OutboxEvent.objects.filter(pk=event_id).exists()


def _account_visible(item: OutboxEvent, *, user: User) -> bool:
    payload = item.payload or {}
    return str(payload.get("user_id", "")) == user.public_id or (
        item.aggregate_type == "account" and item.aggregate_ref == user.public_id
    )


def _visible(item: OutboxEvent, *, user: User, portal: str) -> bool:
    payload = item.payload or {}
    course_id = str(payload.get("course_id", ""))
    task_id = str(payload.get("task_id", ""))
    if portal == "PLATFORM":
        return True
    if portal == "TEACHING":
        if not course_id:
            return _account_visible(item, user=user)
        course = Course.objects.filter(public_id=course_id).first()
        return bool(
            course
            and has_course_capability(
                course=course,
                actor=user,
                capability=CourseStaffGrant.Capability.VIEW_PROGRESS,
            )
        )
    if task_id:
        return ExperimentTask.objects.filter(
            public_id=task_id,
            student=user,
            enrollment__status=Enrollment.Status.ACTIVE,
        ).exists()
    session_id = str(payload.get("session_id", ""))
    if session_id:
        from apps.workspaces.models import WorkspaceSession

        return WorkspaceSession.objects.filter(
            public_id=session_id,
            student=user,
            task__enrollment__status=Enrollment.Status.ACTIVE,
        ).exists()
    if course_id:
        return Enrollment.objects.filter(
            course__public_id=course_id, student=user, status="ACTIVE"
        ).exists()
    return _account_visible(item, user=user)


def _redis_replay(
    *, user: User, portal: str, last_id: str
) -> list[tuple[str, str, dict[str, object], str]]:
    """Read the bounded Redis window when available; MySQL remains the source of truth."""
    try:
        entries = cast(
            list[tuple[str, dict[str, str]]],
            Redis.from_url(settings.REDIS_URL, decode_responses=True).xrange(
                settings.OUTBOX_REDIS_STREAM, min="-", max="+", count=500
            ),
        )
    except Exception:
        return []
    values: list[tuple[str, str, dict[str, object], str]] = []
    for _stream_id, fields in entries:
        event_id = f"{fields.get('occurred_at', '')}|{fields.get('event_id', '')}"
        if last_id and event_id <= last_id:
            continue
        payload = json.loads(str(fields.get("payload", "{}")))
        item = OutboxEvent(
            event_type=str(fields.get("event_type", "")),
            aggregate_type=str(fields.get("aggregate_type", "")),
            aggregate_ref=str(fields.get("aggregate_ref", "")),
            payload=payload,
            trace_id=str(fields.get("trace_id", "")),
        )
        if _visible(item, user=user, portal=portal):
            values.append((event_id, item.event_type, payload, item.trace_id))
    return values


def _event_stream(*, trace_id: str, request: Request) -> Iterator[bytes]:
    portal = str(getattr(request, "portal", ""))
    user: User = request.user  # type: ignore[assignment]
    last_id = request.headers.get("Last-Event-ID", "")
    cursor_time = _cursor_time(last_id)
    yield f": stream-ready trace_id={trace_id}\n\n".encode()
    if last_id and cursor_time is None:
        yield (
            b"event: resync.required\n"
            b'data: {"code":"SSE_RESYNC_REQUIRED","reason":"invalid_cursor"}\n\n'
        )
        return
    if last_id and not _cursor_exists(last_id):
        yield (
            b"event: resync.required\n"
            b'data: {"code":"SSE_CURSOR_EXPIRED","reason":"cursor_expired"}\n\n'
        )
        return
    emitted_ids: set[str] = set()
    for event_id, event_type, payload, event_trace_id in _redis_replay(
        user=user, portal=portal, last_id=last_id
    ):
        emitted_ids.add(event_id)
        encoded = json.dumps(
            {**payload, "trace_id": event_trace_id},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        yield (
            f"id: {event_id}\n"
            f"event: {event_type}\n"
            f"data: {encoded}\n\n"
        ).encode()
    events = OutboxEvent.objects.all().order_by("created_at", "id")
    if cursor_time is not None:
        events = events.filter(created_at__gte=cursor_time)
    for item in events[:500]:
        event_id = _event_id(item)
        if event_id in emitted_ids or (last_id and event_id <= last_id):
            continue
        if not _visible(item, user=user, portal=portal):
            continue
        data = {
            **(item.payload or {}),
            "trace_id": item.trace_id,
            "aggregate_ref": item.aggregate_ref,
        }
        yield (
            f"id: {event_id}\n"
            f"event: {item.event_type}\n"
            f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"
        ).encode()
    yield b": heartbeat\n\n"


class EventStreamView(APIView):
    authentication_classes = [PortalSessionAuthentication]
    permission_classes = [IsAuthenticatedAccount]

    @extend_schema(
        tags=["events"],
        summary="Portal event stream",
        responses={
            (200, "text/event-stream"): OpenApiResponse(description="Server-sent event stream")
        },
        extensions={"x-portals": ["USER", "TEACHING", "PLATFORM"]},
    )
    def get(self, request: Request) -> StreamingHttpResponse:
        response = StreamingHttpResponse(
            _event_stream(trace_id=getattr(request, "trace_id", ""), request=request),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache, no-transform"
        response["X-Accel-Buffering"] = "no"
        return response
