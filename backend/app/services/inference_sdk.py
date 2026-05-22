from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx

from .llm_providers import ProviderUsage

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _trim(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[:limit].rstrip()}..."


@dataclass
class InferenceEventContext:
    request_id: str
    conversation_id: str
    session_id: str
    provider: str
    model: str
    request_started_at: datetime
    input_preview: str | None
    metadata: dict[str, Any]


class InferenceSDK:
    def __init__(
        self,
        ingestion_url: str,
        input_preview_chars: int = 320,
        output_preview_chars: int = 320,
    ):
        self.ingestion_url = ingestion_url
        self.input_preview_chars = input_preview_chars
        self.output_preview_chars = output_preview_chars
        self.client = httpx.AsyncClient(timeout=10.0)

    def begin_event(
        self,
        conversation_id: str,
        session_id: str,
        provider: str,
        model: str,
        input_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> InferenceEventContext:
        return InferenceEventContext(
            request_id=str(uuid4()),
            conversation_id=conversation_id,
            session_id=session_id,
            provider=provider,
            model=model,
            request_started_at=_utcnow(),
            input_preview=_trim(input_text, self.input_preview_chars),
            metadata=metadata or {},
        )

    async def emit_started(self, event: InferenceEventContext) -> None:
        payload = {
            "request_id": event.request_id,
            "conversation_id": event.conversation_id,
            "session_id": event.session_id,
            "event_type": "started",
            "status": "started",
            "provider": event.provider,
            "model": event.model,
            "request_started_at": event.request_started_at.isoformat(),
            "request_ended_at": None,
            "latency_ms": None,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "input_preview": event.input_preview,
            "output_preview": None,
            "error_type": None,
            "error_message": None,
            "metadata": event.metadata,
        }
        await self._post(payload)

    async def emit_finished(
        self,
        event: InferenceEventContext,
        status: str,
        output_text: str | None,
        usage: ProviderUsage | None = None,
        error: Exception | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        ended_at = _utcnow()
        latency_ms = int((ended_at - event.request_started_at).total_seconds() * 1000)
        usage = usage or ProviderUsage()
        payload = {
            "request_id": event.request_id,
            "conversation_id": event.conversation_id,
            "session_id": event.session_id,
            "event_type": status if status in {"completed", "error", "cancelled"} else "completed",
            "status": status,
            "provider": event.provider,
            "model": event.model,
            "request_started_at": event.request_started_at.isoformat(),
            "request_ended_at": ended_at.isoformat(),
            "latency_ms": latency_ms,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
            "input_preview": event.input_preview,
            "output_preview": _trim(output_text, self.output_preview_chars),
            "error_type": type(error).__name__ if error else None,
            "error_message": str(error)[:1000] if error else None,
            "metadata": {**event.metadata, **(metadata or {})},
        }
        await self._post(payload)

    async def _post(self, payload: dict[str, Any]) -> None:
        try:
            response = await self.client.post(self.ingestion_url, json=payload)
            if response.status_code >= 300:
                logger.warning("Inference log ingestion failed: %s %s", response.status_code, response.text[:200])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Inference log post failed: %s", exc)

    async def aclose(self) -> None:
        await self.client.aclose()
