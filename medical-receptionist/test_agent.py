"""Mocked AI provider regression tests; never calls external APIs."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("JWT_SECRET", "test-only-secret-for-unit-tests")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_ci.db")

import agent as agent_module
from agent import Agent


def fake_groq_client(response_text='{"intent":"FAQ","response":"Fallback response"}', error=None):
    create = Mock()
    if error is not None:
        create.side_effect = error
    else:
        create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=response_text))]
        )
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def fake_agent(gemini_text='{"intent":"GREETING","response":"Hello"}', gemini_error=None, groq_error=None):
    instance = Agent.__new__(Agent)
    instance.gemini_api_key = "test-gemini-key"
    instance.groq_api_key = "test-groq-key"
    instance.system_prompt = "Test system prompt"
    instance.detect_language = lambda _text: "English"

    def generate_content(**_kwargs):
        if gemini_error is not None:
            raise gemini_error
        return SimpleNamespace(text=gemini_text)

    instance.gemini_client = SimpleNamespace(models=SimpleNamespace(
        generate_content=Mock(side_effect=generate_content)
    ))
    instance.groq_client = fake_groq_client(error=groq_error)
    return instance


class AgentProviderTests(unittest.TestCase):
    def test_gemini_success_uses_configured_model(self):
        instance = fake_agent()
        with patch.object(agent_module, "GEMINI_MODEL", "test-gemini-model"):
            result = instance.generate_response("hello")
        self.assertEqual(result["intent"], "GREETING")
        instance.gemini_client.models.generate_content.assert_called_once()
        self.assertEqual(
            instance.gemini_client.models.generate_content.call_args.kwargs["model"],
            "test-gemini-model",
        )

    def test_malformed_gemini_json_falls_back_to_groq(self):
        instance = fake_agent(gemini_text="this is not JSON")
        with patch.object(agent_module, "GROQ_MODEL", "test-groq-model"):
            result = instance.generate_response("hello")
        self.assertEqual(result["intent"], "FAQ")
        self.assertEqual(
            instance.groq_client.chat.completions.create.call_args.kwargs["model"],
            "test-groq-model",
        )

    def test_gemini_timeout_falls_back_to_groq(self):
        instance = fake_agent(gemini_error=TimeoutError("simulated timeout"))
        result = instance.generate_response("hello")
        self.assertEqual(result["intent"], "FAQ")
        instance.groq_client.chat.completions.create.assert_called_once()

    def test_gemini_provider_error_falls_back_to_groq(self):
        instance = fake_agent(gemini_error=RuntimeError("simulated provider error"))
        result = instance.generate_response("hello")
        self.assertEqual(result["intent"], "FAQ")

    def test_patient_name_extraction_uses_same_configured_gemini_model(self):
        instance = fake_agent(gemini_text="Rahul Sharma")
        with patch.object(agent_module, "GEMINI_MODEL", "test-gemini-model"):
            result = instance.extract_patient_data("My name is Rahul Sharma and phone 9876543210")
        self.assertEqual(result["name"], "Rahul Sharma")
        self.assertEqual(result["phone"], "9876543210")
        self.assertEqual(
            instance.gemini_client.models.generate_content.call_args.kwargs["model"],
            "test-gemini-model",
        )


if __name__ == "__main__":
    unittest.main()
