from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from anthropic import NOT_GIVEN, AsyncAnthropic
from openai import AsyncOpenAI

from ..config import Settings


class ProviderError(Exception):
    pass


@dataclass
class ProviderUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass
class ProviderResponse:
    text: str
    provider: str
    model: str
    usage: ProviderUsage
    metadata: dict[str, Any] | None = None


class ProviderRouter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._openai = AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        self._anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key) if settings.anthropic_api_key else None
        self._gemini_api_key = settings.gemini_api_key.strip() if settings.gemini_api_key else None

    def provider_descriptors(self) -> list[dict[str, Any]]:
        return [
            {"name": "gemini", "configured": self._gemini_api_key is not None, "default_model": "gemini-3.5-flash"},
            {"name": "openai", "configured": self._openai is not None, "default_model": "gpt-4.1-mini"},
            {
                "name": "anthropic",
                "configured": self._anthropic is not None,
                "default_model": "claude-3-5-sonnet-20241022",
            },
            {"name": "mock", "configured": True, "default_model": "mock-echo-v1"},
        ]

    async def generate(
        self,
        provider: str,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int = 900,
    ) -> ProviderResponse:
        provider_key = provider.lower().strip()
        if provider_key == "gemini":
            return await self._generate_gemini(model=model, messages=messages, max_tokens=max_tokens)
        if provider_key == "openai":
            return await self._generate_openai(model=model, messages=messages, max_tokens=max_tokens)
        if provider_key == "anthropic":
            return await self._generate_anthropic(model=model, messages=messages, max_tokens=max_tokens)
        if provider_key == "mock":
            return self._generate_mock(model=model, messages=messages)
        raise ProviderError(f"Unsupported provider '{provider}'. Supported: gemini, openai, anthropic, mock.")

    async def _generate_gemini(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> ProviderResponse:
        if not self._gemini_api_key:
            raise ProviderError("GEMINI_API_KEY is missing. Configure it in .env or switch provider.")

        system_chunks: list[str] = []
        gemini_contents: list[dict[str, Any]] = []
        for message in messages:
            role = message["role"]
            content = message["content"]
            if role == "system":
                system_chunks.append(content)
                continue
            if role not in {"user", "assistant"}:
                continue
            gemini_role = "model" if role == "assistant" else "user"
            gemini_contents.append({"role": gemini_role, "parts": [{"text": content}]})

        if not gemini_contents:
            raise ProviderError("Gemini request has no user/assistant content to send.")

        model_name = model.strip() if model.strip() else "gemini-3.5-flash"
        model_path = model_name if model_name.startswith("models/") else f"models/{model_name}"
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/{model_path}:generateContent"
        payload: dict[str, Any] = {
            "contents": gemini_contents,
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens},
        }
        if system_chunks:
            payload["systemInstruction"] = {"parts": [{"text": "\n".join(system_chunks).strip()}]}

        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
                response = await client.post(
                    endpoint,
                    headers={"x-goog-api-key": self._gemini_api_key, "Content-Type": "application/json"},
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Gemini network error: {exc}") from exc

        if response.status_code >= 300:
            err_msg = self._extract_gemini_error(response)
            raise ProviderError(f"Gemini API error ({response.status_code}): {err_msg}")

        data = response.json()
        text = self._extract_gemini_text(data)
        if not text:
            raise ProviderError("Gemini returned an empty response.")

        usage_meta = data.get("usageMetadata") or {}
        usage = ProviderUsage(
            prompt_tokens=usage_meta.get("promptTokenCount"),
            completion_tokens=usage_meta.get("candidatesTokenCount"),
            total_tokens=usage_meta.get("totalTokenCount"),
        )
        return ProviderResponse(text=text, provider="gemini", model=model_name, usage=usage)

    @staticmethod
    def _extract_gemini_text(data: dict[str, Any]) -> str:
        candidates = data.get("candidates") or []
        text_parts: list[str] = []
        for candidate in candidates:
            content = candidate.get("content") or {}
            parts = content.get("parts") or []
            for part in parts:
                part_text = part.get("text")
                if part_text:
                    text_parts.append(part_text)
        return "".join(text_parts).strip()

    @staticmethod
    def _extract_gemini_error(response: httpx.Response) -> str:
        with_error = None
        try:
            body = response.json()
            with_error = (body.get("error") or {}).get("message")
        except ValueError:
            with_error = None
        if with_error:
            return with_error
        raw = response.text.strip()
        return raw[:360] if raw else "unknown error"

    async def _generate_openai(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> ProviderResponse:
        if self._openai is None:
            raise ProviderError("OPENAI_API_KEY is missing. Configure it in .env or switch provider to 'mock'.")

        response = await self._openai.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.2,
            timeout=self.settings.request_timeout_seconds,
        )
        text = ""
        if response.choices:
            text = response.choices[0].message.content or ""

        usage = ProviderUsage(
            prompt_tokens=getattr(response.usage, "prompt_tokens", None),
            completion_tokens=getattr(response.usage, "completion_tokens", None),
            total_tokens=getattr(response.usage, "total_tokens", None),
        )
        return ProviderResponse(text=text, provider="openai", model=model, usage=usage)

    async def _generate_anthropic(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> ProviderResponse:
        if self._anthropic is None:
            raise ProviderError("ANTHROPIC_API_KEY is missing. Configure it in .env or switch provider to 'mock'.")

        system_chunks: list[str] = []
        anthropic_messages: list[dict[str, Any]] = []
        for message in messages:
            role = message["role"]
            content = message["content"]
            if role == "system":
                system_chunks.append(content)
                continue
            if role not in {"user", "assistant"}:
                continue
            anthropic_messages.append({"role": role, "content": content})

        system_prompt = "\n".join(system_chunks).strip()
        response = await self._anthropic.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0.2,
            system=system_prompt if system_prompt else NOT_GIVEN,
            messages=anthropic_messages,
            timeout=self.settings.request_timeout_seconds,
        )

        text_blocks = [part.text for part in response.content if getattr(part, "type", "") == "text"]
        text = "".join(text_blocks)
        usage = ProviderUsage(
            prompt_tokens=getattr(response.usage, "input_tokens", None),
            completion_tokens=getattr(response.usage, "output_tokens", None),
            total_tokens=None,
        )
        if usage.prompt_tokens is not None and usage.completion_tokens is not None:
            usage.total_tokens = usage.prompt_tokens + usage.completion_tokens

        return ProviderResponse(text=text, provider="anthropic", model=model, usage=usage)

    def _generate_mock(self, model: str, messages: list[dict[str, str]]) -> ProviderResponse:
        last_user_message = ""
        for message in reversed(messages):
            if message["role"] == "user":
                last_user_message = message["content"]
                break

        preview = " ".join(last_user_message.strip().split())
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        text = (
            "Mock provider response.\n"
            f"Time: {now}\n"
            f"You said: {preview[:280] if preview else '(empty)'}\n"
            "This path keeps the product testable even without external API credentials."
        )
        token_count = max(1, int(len(text) / 4))
        usage = ProviderUsage(prompt_tokens=max(1, int(len(last_user_message) / 4)), completion_tokens=token_count)
        usage.total_tokens = usage.prompt_tokens + usage.completion_tokens
        return ProviderResponse(text=text, provider="mock", model=model or "mock-echo-v1", usage=usage)
