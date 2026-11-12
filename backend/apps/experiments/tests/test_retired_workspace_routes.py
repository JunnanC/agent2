import pytest
from django.test import Client
from django.urls import Resolver404, resolve


@pytest.mark.parametrize("path", [
    "tasks/task/start", "tasks/task/retry", "tasks/task/enter", "tasks/task/workbench",
    "tasks/task/workspace-sessions", "workspace-sessions/session/renew",
    "tasks/task/workspace-snapshot", "tasks/task/workspace-storage-jobs",
    "tasks/task/checkpoints", "tasks/task/execution-runs", "tasks/task/provisioning-job",
    "platform/workspaces/sessions", "student/task-runtimes/runtime/stop",
    "tasks/task/report-draft", "tasks/task/submit-report", "tasks/task/complete",
])
def test_retired_workspace_api_is_not_routed(path: str) -> None:
    assert resolve(f"/api/v2/{path}").url_name == "api-not-found"


@pytest.mark.parametrize("path", ["/workspace/session/webide/", "/internal/workspace-authorize"])
def test_retired_gateway_is_not_routed(path: str) -> None:
    with pytest.raises(Resolver404):
        resolve(path)
    assert Client().get(path).status_code == 404


def test_assessment_and_metrics_routes_remain() -> None:
    assert resolve("/api/v2/tasks/task/assessment").func.view_class.__name__ == "AssessmentView"
    assert resolve("/internal/metrics").url_name == "metrics"
