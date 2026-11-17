from unittest.mock import patch

import pytest

from apps.analytics.tasks import rebuild_analytics, refresh_projection, replay_projection


@pytest.mark.parametrize("task", [rebuild_analytics, refresh_projection, replay_projection])
def test_projection_retries_transient_failure(task):
    with (
        patch(
            "apps.analytics.tasks.rebuild_course_analytics",
            side_effect=[RuntimeError("temporary"), 7],
        ) as rebuild,
        patch("apps.analytics.tasks.append_failure") as record_failure,
    ):
        result = task.apply(kwargs={"trace_id": "retry-test"}, throw=False)
    assert result.get() == 7
    assert rebuild.call_count == 2
    record_failure.assert_called_once()


@pytest.mark.parametrize("task", [rebuild_analytics, refresh_projection, replay_projection])
def test_projection_stops_after_two_retries(task):
    with (
        patch(
            "apps.analytics.tasks.rebuild_course_analytics", side_effect=RuntimeError("unavailable")
        ) as rebuild,
        patch("apps.analytics.tasks.append_failure"),
    ):
        result = task.apply(throw=False)
    assert result.failed()
    assert isinstance(result.result, RuntimeError)
    assert rebuild.call_count == 3
