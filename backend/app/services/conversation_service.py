from __future__ import annotations

from ..models import ChatMessage


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / 4))


def derive_title(text: str) -> str:
    trimmed = " ".join(text.strip().split())
    if not trimmed:
        return "New conversation"
    if len(trimmed) <= 44:
        return trimmed
    return f"{trimmed[:41].rstrip()}..."


def build_context_messages(messages: list[ChatMessage], limit: int) -> list[dict[str, str]]:
    if limit <= 0:
        return []
    selected = messages[-limit:]
    return [{"role": message.role, "content": message.content} for message in selected]


def chunk_text(text: str, chunk_size: int = 28) -> list[str]:
    if not text:
        return [""]
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
