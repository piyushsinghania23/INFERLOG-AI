from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    title: str | None = None
    provider: str | None = None
    model: str | None = None


class MessageView(BaseModel):
    id: str
    role: str
    content: str
    token_estimate: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationSummary(BaseModel):
    id: str
    title: str
    status: str
    provider: str | None = None
    model: str | None = None
    created_at: datetime
    updated_at: datetime
    last_message_preview: str | None = None


class ConversationDetail(BaseModel):
    id: str
    title: str
    status: str
    provider: str | None = None
    model: str | None = None
    created_at: datetime
    updated_at: datetime
    messages: list[MessageView]


class ChatStreamRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    provider: str | None = None
    model: str | None = None


class InferenceLogPayload(BaseModel):
    request_id: str
    conversation_id: str
    session_id: str
    event_type: Literal["started", "completed", "error", "cancelled"]
    status: str
    provider: str
    model: str
    request_started_at: datetime
    request_ended_at: datetime | None = None
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    input_preview: str | None = Field(default=None, max_length=2000)
    output_preview: str | None = Field(default=None, max_length=2000)
    error_type: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] | None = None


class ProviderDescriptor(BaseModel):
    name: str
    configured: bool
    default_model: str


class ThroughputPoint(BaseModel):
    minute: str
    count: int


class DashboardSummary(BaseModel):
    window_hours: int
    total_requests: int
    completed_requests: int
    error_requests: int
    cancelled_requests: int
    error_rate: float
    avg_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    total_tokens: int
    queue_depth: int
    throughput: list[ThroughputPoint]
    errors_by_type: dict[str, int]


class InferenceLogView(BaseModel):
    request_id: str
    conversation_id: str
    event_type: str
    status: str
    provider: str
    model: str
    latency_ms: int | None = None
    total_tokens: int | None = None
    error_type: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
