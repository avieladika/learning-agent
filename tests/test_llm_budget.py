import unittest
from unittest.mock import Mock, patch

from backend.agent.llm_client import LLMClient
from backend.utils.token_budget import TokenCounter


class LLMBudgetTests(unittest.TestCase):
    def test_large_context_fits_request_budget(self):
        # No provider calls or tokenizer downloads during regression tests.
        with patch.object(TokenCounter, "_load_tokenizer", return_value=None):
            client = LLMClient(api_key="test")
        create = Mock()
        create.return_value.choices = [Mock(message=Mock(content='{"sufficient": true}'))]
        client.client.chat.completions.create = create

        for method in (client.generate_answer_from_string, client.assess_evidence):
            for text in ("training context " * 10000, "שאלת אימון " * 10000):
                method(text, text)
                request = create.call_args.kwargs
                prompt_tokens = sum(
                    client.token_counter.count(message["content"]) + 4
                    for message in request["messages"]
                )
                self.assertLessEqual(
                    prompt_tokens + request["max_completion_tokens"] + client.budgets.safety_margin,
                    8000,
                )
                self.assertIn("Context:", request["messages"][1]["content"])
                self.assertIn("Question:", request["messages"][1]["content"])


if __name__ == "__main__":
    unittest.main()
