"""Token counting and deterministic prompt-budget helpers."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable


@dataclass(frozen=True)
class TokenBudgets:
    # Fit the observed 8,000-token provider limit, including answer headroom.
    system: int = 1_000
    history: int = 1_000
    transcripts: int = 3_000
    question: int = 500
    answer: int = 2_000
    safety_margin: int = 500

    @property
    def total(self) -> int:
        return sum((self.system, self.history, self.transcripts, self.question, self.answer, self.safety_margin))


class TokenCounter:
    """Use the model tokenizer when cached; retain a safe offline fallback."""

    def __init__(self, model: str = "openai/gpt-oss-120b"):
        self.model = model
        self._tokenizer = self._load_tokenizer(model)

    @staticmethod
    @lru_cache(maxsize=4)
    def _load_tokenizer(model: str):
        try:
            from transformers import AutoTokenizer

            # Never make server startup depend on a Hugging Face download. A user
            # can pre-cache the exact tokenizer and it will be picked up here.
            return AutoTokenizer.from_pretrained(model, local_files_only=True)
        except Exception:
            return None

    def encode(self, text: str) -> list:
        if self._tokenizer is not None:
            return self._tokenizer.encode(text, add_special_tokens=False)
        # Conservative approximation for English and punctuation. It purposely
        # over-counts compared with the usual ~4 characters/token rule.
        return list(range((len(text.encode("utf-8")) + 2) // 3))

    def count(self, text: str) -> int:
        return len(self.encode(text or ""))

    def truncate(self, text: str, limit: int) -> str:
        if limit <= 0 or not text:
            return ""
        if self._tokenizer is not None:
            ids = self._tokenizer.encode(text, add_special_tokens=False)
            return self._tokenizer.decode(ids[:limit], skip_special_tokens=True)
        # Match the conservative fallback without cutting invalid UTF-8.
        return text.encode("utf-8")[: limit * 3].decode("utf-8", errors="ignore")


def trim_history(messages: Iterable[dict], counter: TokenCounter, limit: int) -> list[dict]:
    """Keep the newest complete user/assistant turns within the history budget."""
    cleaned: list[dict] = []
    for message in messages:
        role = str(message.get("role", "")).lower()
        content = str(message.get("content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            continue
        if role == "assistant":
            # Citations are retrieval output, not useful conversational memory.
            content = content.split("\n\n## Sources", 1)[0]
        cleaned.append({"role": role, "content": content})

    turns: list[list[dict]] = []
    for message in cleaned:
        if message["role"] == "user" or not turns:
            turns.append([message])
        else:
            turns[-1].append(message)

    kept: list[list[dict]] = []
    used = 0
    for turn in reversed(turns):
        turn_cost = sum(counter.count(item["content"]) + 4 for item in turn)
        if used + turn_cost > limit:
            break
        kept.append(turn)
        used += turn_cost
    return [message for turn in reversed(kept) for message in turn]
