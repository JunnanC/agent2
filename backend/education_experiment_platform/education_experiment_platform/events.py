import json
from collections.abc import Iterator
from datetime import datetime

from apps.accounts.authentication import PortalSessionAuthentication
from apps.accounts.models import User
from apps.accounts.permissions import IsAuthenticatedAccount
from apps.core.models import OutboxEvent
from apps.courses.models import CourseStaff, Enrollment
from apps.experiments.models import ExperimentTask
from django.http import StreamingHttpResponse
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.request import Request
from rest_framework.views import APIView


def _event_id(item: OutboxEvent) -> str:
    return f"{item.created_at.isoformat()}|{item.id}"


def _cursor_time(value: str) -> datetime | None:
    if not value or "|" not in value:
        return None
    return parse_datetime(value.split("|", 1)[0])


def _visible(item: OutboxEvent, *, user: User, portal: str) -> bool:
    payload = item.payload or {}
    course_id = str(payload.get("course_id", ""))
    task_id = str(payload.get("task_id", ""))
    if portal == "PLATFORM":
        return True
    if portal == "TEACHING":
        if not course_id:
            return item.aggregate_type in {"account", "notification"}
        return CourseStaff.objects.filter(
            course__public_id=course_id, user=user, status=CourseStaff.Status.ACTIVE
        ).exists()
    if task_id:
        return ExperimentTask.objects.filter(public_id=task_id, student=user).exists()
    session_id = str(payload.get("session_id", ""))
    if session_id:
        from apps.workspaces.models import WorkspaceSession

        return WorkspaceSession.objects.filter(public_id=session_id, student=user).exists()
    if course_id:
        return Enrollment.objects.filter(
            course__public_id=course_id, student=user, status="ACTIVE"
        ).exists()
    return item.aggregate_type in {"account", "notification"}


def _event_stream(*, trace_id: str, request: Request) -> Iterator[bytes]:
    portal = str(getattr(request, "portal", ""))
    user: User = request.user  # type: ignore[assignment]
    last_id = request.headers.get("Last-Event-ID", "")
    cursor_time = _cursor_time(last_id)
    yield f": stream-ready trace_id={trace_id}\n\n".encode()
    if last_id and cursor_time is None:
        yield b'event: resync.required\ndata: {"reason":"invalid_cursor"}\n\n'
        return
    events = OutboxEvent.objects.all().order_by("created_at", "id")
    if cursor_time is not None:
        events = events.filter(created_at__gte=cursor_time)
    emitted = 0
    for item in events[:500]:
        event_id = _event_id(item)
        if last_id and event_id <= last_id:
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
        emitted += 1
    if emitted == 0 and last_id and cursor_time is not None:
        yield b'event: resync.required\ndata: {"reason":"replay_window"}\n\n'
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
