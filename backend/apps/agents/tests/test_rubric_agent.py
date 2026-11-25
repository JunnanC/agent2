import json
from decimal import Decimal
from unittest import TestCase
from unittest.mock import Mock, patch

from django.test import override_settings

from apps.agents.rubric_agent import (
    CriterionAssessment,
    RubricAgentConfigurationError,
    RubricAssessment,
    assess_submission,
    structured_chat_model,
)


class RubricAgentTests(TestCase):
    @override_settings(
        AI_API_KEY="test-key",
        AI_BASE_URL="https://llm.example.test/v1",
        AI_MODEL_NAME="test-model",
    )
    def test_builds_langchain_agent_and_returns_structured_assessment(self) -> None:
        assessment = RubricAssessment(
            criteria=[
                CriterionAssessment(
                    criterion_id="criterion-1",
                    score=Decimal("8.50"),
                    rationale="The result is explained.",
                    evidence="The report states the observed result.",
                )
            ]
        )
        agent = Mock()
        agent.invoke.return_value = {"structured_response": assessment}
        with (
            patch("langchain.agents.create_agent", return_value=agent) as create_agent,
            patch("langchain_openai.ChatOpenAI") as chat_model,
        ):
            result = assess_submission(
                report="A student report.",
                rubric=[{"criterion_id": "criterion-1", "max_score": "10.00"}],
            )

        self.assertIs(result, assessment)
        chat_model.assert_called_once_with(
            model="test-model",
            api_key="test-key",
            base_url="https://llm.example.test/v1",
            temperature=0,
            timeout=60,
            max_retries=1,
            extra_body=None,
        )
        create_agent.assert_called_once()
        message = create_agent.return_value.invoke.call_args.args[0]["messages"][0]
        payload = json.loads(message["content"])
        self.assertEqual(payload["submission"], "A student report.")
        self.assertEqual(payload["rubric"][0]["criterion_id"], "criterion-1")

    @override_settings(
        AI_API_KEY="test-key",
        AI_BASE_URL="https://api.deepseek.com/v1",
        AI_MODEL_NAME="test-model",
    )
    def test_deepseek_disables_thinking_for_structured_output(self) -> None:
        with patch("langchain_openai.ChatOpenAI") as chat_model:
            structured_chat_model()

        self.assertEqual(chat_model.call_args.kwargs["extra_body"], {
            "thinking": {"type": "disabled"},
        })

    @override_settings(
        AI_API_KEY="",
        AI_BASE_URL="",
        AI_MODEL_NAME="",
    )
    def test_requires_provider_configuration(self) -> None:
        with self.assertRaises(RubricAgentConfigurationError):
            assess_submission(report="report", rubric=[])
