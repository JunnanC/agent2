from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class RetrievalCandidate:
    source_version_id: str
    title: str
    snippet: str
    score: float
    asset_id: str | None = None
    audience: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelReply:
    body: str
    token_count: int
    citation_status: str
    tool_requests: list[dict[str, Any]] = field(default_factory=list)
    cost_minor: int = 0
    model_route: str = ""


class KnowledgeRetriever(Protocol):
    def search(
        self,
        *,
        course_id: str,
        knowledge_base_id: str | None,
        query: str,
        task_id: str | None,
        student_id: str | None = None,
        enrollment_id: str | None = None,
        source_version_ids: list[str] | None = None,
        limit: int = 5,
    ) -> list[RetrievalCandidate]: ...

    def rebuild(self, *, source_version_id: str) -> int: ...


class ModelGateway(Protocol):
    def complete(
        self,
        *,
        mode: str,
        prompt: str,
        context: list[RetrievalCandidate],
        model_route: str,
        token_budget: int,
    ) -> ModelReply: ...


class ToolExecutor(Protocol):
    def execute(
        self, *, tool_name: str, arguments: dict[str, Any], scope: dict[str, Any]
    ) -> dict[str, Any]: ...
