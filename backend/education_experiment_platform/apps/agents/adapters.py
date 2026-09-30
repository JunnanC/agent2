import hashlib
import re
import time
from dataclasses import replace
from typing import Any

from apps.core.models import ObjectAsset

from .models import AgentSourceVersion, ModelRoute
from .ports import ModelReply, RetrievalCandidate


def source_text(version: AgentSourceVersion) -> str:
    material = getattr(version, "material_version", None)
    if material is not None and material.status == "PUBLISHED":
        return material.text_content
    if version.object_asset is not None:
        stored = None
        try:
            from apps.core.object_storage import object_storage

            stored = object_storage().open_object(
                bucket=version.object_asset.bucket,
                object_key=version.object_asset.object_key,
                version_id=version.object_asset.object_version,
            )
            value = stored.body.read()
            return value.decode("utf-8") if isinstance(value, bytes) else str(value)
        except Exception:
            return ""
        finally:
            if stored is not None:
                stored.body.close()
    return ""


class KeywordKnowledgeRetriever:
    """Deterministic, rebuildable baseline retriever.

    The index is deliberately derived from MySQL source-version facts and is rebuilt
    on demand. It never becomes an authorization source.
    """

    def __init__(self) -> None:
        self._index: dict[str, list[str]] = {}

    def rebuild(self, *, source_version_id: str) -> int:
        try:
            version = AgentSourceVersion.objects.select_related("source", "object_asset").get(
                public_id=source_version_id
            )
        except AgentSourceVersion.DoesNotExist:
            return 0
        text = source_text(version).strip()
        chunks = [
            item.strip() for item in re.split(r"\n{2,}|(?<=[。！？.!?])\s+", text) if item.strip()
        ]
        self._index[source_version_id] = chunks
        return len(chunks)

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
    ) -> list[RetrievalCandidate]:
        versions = AgentSourceVersion.objects.select_related(
            "source", "object_asset", "material_version"
        ).filter(
            source__course__public_id=course_id,
            status=AgentSourceVersion.Status.INDEXED,
            source__status="ACTIVE",
            source__knowledge_base__status="ACTIVE",
        )
        if knowledge_base_id:
            versions = versions.filter(source__knowledge_base__public_id=knowledge_base_id)
        if source_version_ids is not None:
            versions = versions.filter(public_id__in=source_version_ids)
        terms = {term.lower() for term in re.findall(r"[\w\u4e00-\u9fff]+", query) if term.strip()}
        candidates: list[RetrievalCandidate] = []
        for version in versions:
            if version.object_asset_id and (
                version.object_asset.status != ObjectAsset.Status.ACTIVE
                or version.object_asset.scan_status != ObjectAsset.ScanStatus.CLEAN
            ):
                continue
            audience = version.audience or {}
            if audience.get("course_id") not in {None, course_id}:
                continue
            if audience.get("student_ids") and student_id not in audience["student_ids"]:
                continue
            if audience.get("enrollment_ids") and enrollment_id not in audience["enrollment_ids"]:
                continue
            if audience.get("task_ids") and task_id not in audience["task_ids"]:
                continue
            chunks = self._index.get(version.public_id)
            if chunks is None:
                self.rebuild(source_version_id=version.public_id)
                chunks = self._index.get(version.public_id, [])
            for chunk in chunks:
                lowered = chunk.lower()
                hits = sum(1 for term in terms if term in lowered)
                if hits <= 0:
                    continue
                candidates.append(
                    RetrievalCandidate(
                        source_version_id=version.public_id,
                        title=version.source.title,
                        snippet=chunk[:1200],
                        score=min(1.0, hits / max(len(terms), 1)),
                        asset_id=(version.object_asset.public_id if version.object_asset else None),
                        audience=audience,
                    )
                )
        candidates.sort(key=lambda item: (-item.score, item.source_version_id, item.snippet))
        return candidates[:limit]


class RuleBasedModelGateway:
    """Safe local adapter used by Compose verification and unit tests."""

    def complete(
        self,
        *,
        mode: str,
        prompt: str,
        context: list[RetrievalCandidate],
        model_route: str,
        token_budget: int,
    ) -> ModelReply:
        del model_route
        if not context:
            return ModelReply(
                body="我没有找到可靠的课程资料来源。请补充资料范围或联系教师。",
                token_count=min(max(len(prompt) // 4, 1), token_budget),
                citation_status="NO_RELIABLE_SOURCE",
            )
        lead = "\n".join(f"[{index}] {item.snippet}" for index, item in enumerate(context, 1))
        if mode == "SOCRATIC_HINT":
            body = f"先检查这些资料中的定义，再说明你的判断依据：\n{lead}"
        elif mode == "REPORT_COACH":
            body = f"可以从结构、证据和缺项三方面检查报告：\n{lead}"
        elif mode == "DEBUG_ASSIST":
            body = f"建议按以下资料逐项验证现象、输入和预期结果：\n{lead}"
        else:
            body = f"根据课程资料：\n{lead}"
        return ModelReply(
            body=body[: max(token_budget * 4, 256)],
            token_count=min(max(len(body) // 4, 1), token_budget),
            citation_status="CITED",
        )


class ApprovedModelGateway:
    """Resolves only platform-approved routes and preserves fallback selection."""

    def complete(
        self,
        *,
        mode: str,
        prompt: str,
        context: list[RetrievalCandidate],
        model_route: str,
        token_budget: int,
    ) -> ModelReply:
        primary = (
            ModelRoute.objects.filter(status=ModelRoute.Status.ACTIVE)
            .filter(public_id=model_route)
            .first()
        )
        if primary is None:
            primary = (
                ModelRoute.objects.filter(status=ModelRoute.Status.ACTIVE, key=model_route)
                .order_by("-version_no")
                .first()
            )
        if primary is None:
            raise RuntimeError("approved model route is unavailable")
        route_ids = [primary.public_id, *primary.fallback_routes]
        for route_id in route_ids:
            route = ModelRoute.objects.filter(
                public_id=route_id, status=ModelRoute.Status.ACTIVE
            ).first()
            if route is None or route.provider != "LOCAL":
                continue
            started = time.monotonic()
            reply = RuleBasedModelGateway().complete(
                mode=mode,
                prompt=prompt,
                context=context,
                model_route=route.public_id,
                token_budget=min(token_budget, route.max_tokens),
            )
            if time.monotonic() - started > route.timeout_seconds:
                continue
            input_tokens = max(1, len(prompt) // 4)
            cost = (
                input_tokens * route.cost_per_1k_input_minor
                + reply.token_count * route.cost_per_1k_output_minor
            ) // 1000
            return replace(reply, cost_minor=cost, model_route=route.public_id)
        raise RuntimeError("all approved model routes are unavailable")


class SafeToolExecutor:
    def execute(
        self, *, tool_name: str, arguments: dict[str, Any], scope: dict[str, Any]
    ) -> dict[str, Any]:
        if tool_name == "read_course_material":
            return {
                "tool": tool_name,
                "course_id": scope.get("course_id"),
                "query": str(arguments.get("query", ""))[:200],
            }
        if tool_name == "read_task_diagnostics":
            return {"tool": tool_name, "task_id": scope.get("task_id"), "diagnostics": []}
        if tool_name == "workspace_draft":
            return {
                "tool": tool_name,
                "task_id": scope.get("task_id"),
                "created": False,
                "preview": True,
            }
        raise ValueError("tool is not implemented by the safe local adapter")


def digest_arguments(arguments: dict[str, Any]) -> str:
    import json

    return hashlib.sha256(
        json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
