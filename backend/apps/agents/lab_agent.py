"""Structured drafting for experiment authors and report reviewers."""

import json
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .rubric_agent import structured_chat_model


class DraftChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(max_length=5000)
    options: list[str] = Field(min_length=2, max_length=6)
    correct_index: int = Field(ge=0, le=5)
    explanation: str = Field(max_length=5000)


class DraftCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: str = Field(max_length=4096)
    output: str = Field(max_length=4096)


class DraftProgramming(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(max_length=5000)
    explanation: str = Field(max_length=5000)
    starter_code: str = Field(max_length=5000)
    samples: list[DraftCase] = Field(min_length=1, max_length=3)
    hidden_cases: list[DraftCase] = Field(min_length=1, max_length=5)


class LabDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    guidance: str = Field(max_length=16000)
    report_requirements: str = Field(max_length=10000)
    questions: list[DraftChoice] = Field(min_length=1, max_length=5)
    programming_questions: list[DraftProgramming] = Field(default_factory=list, max_length=2)


class ReportComment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paragraph: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=1000)


class WordReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    score: Decimal = Field(ge=0, le=999.99, decimal_places=2)
    feedback: str = Field(max_length=1000)
    comments: list[ReportComment] = Field(max_length=50)


def structured_lab_response[T: BaseModel](
    schema: type[T],
    *,
    system: str,
    data: dict[str, Any],
) -> T:
    from langchain.agents import create_agent
    from langchain.agents.structured_output import ToolStrategy

    agent = create_agent(
        model=structured_chat_model(),
        tools=[],
        system_prompt=system,
        response_format=ToolStrategy(schema),
    )
    result = agent.invoke({
        "messages": [
            {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
        ]
    })
    return schema.model_validate(result["structured_response"])
