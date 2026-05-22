from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, select

from .config import settings
from .db import SessionLocal, init_db
from .models import ChatMessage, Conversation, InferenceLog
from .schemas import (
    ChatStreamRequest,
    ConversationCreate,
    ConversationDetail,
    ConversationSummary,
    DashboardSummary,
    InferenceLogPayload,
    InferenceLogView,
    MessageView,
    ProviderDescriptor,
    ThroughputPoint,
)
from .services.conversation_service import (
    build_context_messages,
    chunk_text,
    derive_title,
    estimate_tokens,
)
from .services.ingest_service import persist_inference_log
from .services.inference_sdk import InferenceSDK
from .services.llm_providers import ProviderError, ProviderRouter

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=True)}\n\n"


def _friendly_error_message(exc: Exception) -> str:
    text = str(exc).strip()
    if not text:
        return "Unexpected inference failure."
    compact = " ".join(text.split())
    if len(compact) > 420:
        compact = f"{compact[:417]}..."
    return compact


def _message_view(message: ChatMessage) -> MessageView:
    return MessageView.model_validate(message)


def _conversation_summary(conversation: Conversation, last_preview: str | None) -> ConversationSummary:
    return ConversationSummary(
        id=conversation.id,
        title=conversation.title,
        status=conversation.status,
        provider=conversation.provider,
        model=conversation.model,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        last_message_preview=last_preview,
    )


async def ingestion_worker(app: FastAPI) -> None:
    while True:
        payload = await app.state.ingest_queue.get()
        try:
            with SessionLocal() as db:
                persist_inference_log(db, payload)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to persist inference log")
        finally:
            app.state.ingest_queue.task_done()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    app.state.ingest_queue = asyncio.Queue(maxsize=settings.ingestion_queue_size)
    app.state.cancel_events: dict[str, asyncio.Event] = {}
    app.state.provider_router = ProviderRouter(settings)
    app.state.inference_sdk = InferenceSDK(
        ingestion_url=settings.ingestion_url,
        input_preview_chars=settings.input_preview_chars,
        output_preview_chars=settings.output_preview_chars,
    )
    app.state.ingest_task = asyncio.create_task(ingestion_worker(app))

    yield

    app.state.ingest_task.cancel()
    with suppress(asyncio.CancelledError):
        await app.state.ingest_task
    await app.state.inference_sdk.aclose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/providers", response_model=list[ProviderDescriptor])
def providers(request: Request) -> list[ProviderDescriptor]:
    router: ProviderRouter = request.app.state.provider_router
    return [ProviderDescriptor.model_validate(item) for item in router.provider_descriptors()]


@app.post("/api/conversations", response_model=ConversationSummary)
def create_conversation(payload: ConversationCreate) -> ConversationSummary:
    with SessionLocal() as db:
        conversation = Conversation(
            title=payload.title or "New conversation",
            status="active",
            provider=payload.provider or settings.default_provider,
            model=payload.model or settings.default_model,
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return _conversation_summary(conversation, None)


@app.get("/api/conversations", response_model=list[ConversationSummary])
def list_conversations() -> list[ConversationSummary]:
    with SessionLocal() as db:
        conversations = db.execute(select(Conversation).order_by(desc(Conversation.updated_at))).scalars().all()
        response: list[ConversationSummary] = []
        for conversation in conversations:
            last_message = (
                db.execute(
                    select(ChatMessage)
                    .where(ChatMessage.conversation_id == conversation.id)
                    .order_by(desc(ChatMessage.created_at))
                    .limit(1)
                )
                .scalars()
                .first()
            )
            preview = None
            if last_message:
                preview = " ".join(last_message.content.split())[:90]
            response.append(_conversation_summary(conversation, preview))
        return response


@app.get("/api/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: str) -> ConversationDetail:
    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

        messages = (
            db.execute(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .order_by(ChatMessage.created_at.asc())
            )
            .scalars()
            .all()
        )
        return ConversationDetail(
            id=conversation.id,
            title=conversation.title,
            status=conversation.status,
            provider=conversation.provider,
            model=conversation.model,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            messages=[_message_view(msg) for msg in messages],
        )


@app.post("/api/conversations/{conversation_id}/cancel")
def cancel_conversation(conversation_id: str, request: Request) -> dict[str, bool]:
    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

        event = request.app.state.cancel_events.get(conversation_id)
        cancelled = event is not None
        if event:
            event.set()
            conversation.status = "cancel_requested"
            conversation.updated_at = _utcnow()
            db.commit()

        return {"cancelled": cancelled}


@app.post("/api/conversations/{conversation_id}/messages/stream")
async def stream_conversation_message(
    conversation_id: str,
    payload: ChatStreamRequest,
    request: Request,
) -> StreamingResponse:
    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

        user_message = ChatMessage(
            conversation_id=conversation_id,
            role="user",
            content=payload.message,
            token_estimate=estimate_tokens(payload.message),
        )
        db.add(user_message)
        if conversation.title == "New conversation":
            conversation.title = derive_title(payload.message)
        conversation.status = "active"
        conversation.updated_at = _utcnow()
        if payload.provider:
            conversation.provider = payload.provider
        if payload.model:
            conversation.model = payload.model
        db.commit()

        recent_messages = (
            db.execute(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .order_by(desc(ChatMessage.created_at))
                .limit(settings.context_window_messages)
            )
            .scalars()
            .all()
        )

        provider = (payload.provider or conversation.provider or settings.default_provider).strip().lower()
        model = (payload.model or conversation.model or settings.default_model).strip()

    context_messages = build_context_messages(list(reversed(recent_messages)), settings.context_window_messages)
    llm_messages = [
        {"role": "system", "content": "You are a concise and helpful assistant."},
        *context_messages,
    ]

    cancel_event = asyncio.Event()
    request.app.state.cancel_events[conversation_id] = cancel_event

    sdk: InferenceSDK = request.app.state.inference_sdk
    router: ProviderRouter = request.app.state.provider_router
    event = sdk.begin_event(
        conversation_id=conversation_id,
        session_id=conversation_id,
        provider=provider,
        model=model,
        input_text=payload.message,
        metadata={"context_messages": len(context_messages)},
    )

    async def event_stream():
        assistant_text = ""
        usage = None
        status = "completed"
        assistant_message_id: str | None = None

        yield _sse({"type": "start", "request_id": event.request_id, "provider": provider, "model": model})
        await sdk.emit_started(event)

        try:
            provider_response = await router.generate(provider=provider, model=model, messages=llm_messages)
            usage = provider_response.usage

            for chunk in chunk_text(provider_response.text):
                if cancel_event.is_set():
                    status = "cancelled"
                    break
                assistant_text += chunk
                yield _sse({"type": "chunk", "text": chunk})
                await asyncio.sleep(0.01)

            if status == "cancelled" and not assistant_text:
                assistant_text = "Response cancelled."
            if not assistant_text:
                assistant_text = "(empty response)"

            with SessionLocal() as db:
                assistant_message = ChatMessage(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=assistant_text,
                    token_estimate=estimate_tokens(assistant_text),
                )
                db.add(assistant_message)
                conversation = db.get(Conversation, conversation_id)
                if conversation:
                    conversation.updated_at = _utcnow()
                    conversation.status = "active" if status == "completed" else "cancelled"
                    conversation.provider = provider_response.provider
                    conversation.model = provider_response.model
                db.commit()
                db.refresh(assistant_message)
                assistant_message_id = assistant_message.id

            await sdk.emit_finished(
                event=event,
                status=status,
                output_text=assistant_text,
                usage=usage,
                metadata={"assistant_message_id": assistant_message_id},
            )
            yield _sse({"type": "done", "status": status, "message_id": assistant_message_id})
        except ProviderError as exc:
            await sdk.emit_finished(event=event, status="error", output_text="", usage=usage, error=exc)
            yield _sse({"type": "error", "message": str(exc)})
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unhandled inference error")
            await sdk.emit_finished(event=event, status="error", output_text="", usage=usage, error=exc)
            yield _sse({"type": "error", "message": _friendly_error_message(exc)})
        finally:
            request.app.state.cancel_events.pop(conversation_id, None)

    headers = {"Cache-Control": "no-cache", "Connection": "keep-alive"}
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)


@app.post("/api/ingest/inference", status_code=202)
async def ingest_inference(payload: InferenceLogPayload, request: Request) -> dict[str, Any]:
    queue: asyncio.Queue = request.app.state.ingest_queue
    try:
        queue.put_nowait(payload)
    except asyncio.QueueFull as exc:
        raise HTTPException(status_code=503, detail="Ingestion queue is full") from exc
    return {"queued": True, "queue_depth": queue.qsize()}


@app.get("/api/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(
    request: Request,
    hours: int = Query(default=24, ge=1, le=168),
) -> DashboardSummary:
    since = _utcnow() - timedelta(hours=hours)

    with SessionLocal() as db:
        logs = (
            db.execute(
                select(InferenceLog)
                .where(InferenceLog.request_started_at >= since)
                .where(InferenceLog.event_type.in_(["completed", "error", "cancelled"]))
                .order_by(InferenceLog.request_started_at.asc())
            )
            .scalars()
            .all()
        )

    latencies = [log.latency_ms for log in logs if log.latency_ms is not None]
    sorted_latencies = sorted(latencies)
    p95_latency = None
    if sorted_latencies:
        p95_index = int(0.95 * (len(sorted_latencies) - 1))
        p95_latency = float(sorted_latencies[p95_index])

    completed = [log for log in logs if log.status == "completed"]
    errors = [log for log in logs if log.status == "error"]
    cancelled = [log for log in logs if log.status == "cancelled"]
    total_requests = len(logs)
    error_rate = (len(errors) / total_requests) * 100 if total_requests else 0.0
    total_tokens = sum(log.total_tokens or 0 for log in logs)
    avg_latency = mean(latencies) if latencies else None

    throughput_map: dict[str, int] = {}
    for log in logs:
        minute_key = log.request_started_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
        throughput_map[minute_key] = throughput_map.get(minute_key, 0) + 1

    throughput_points = [
        ThroughputPoint(minute=minute, count=count)
        for minute, count in sorted(throughput_map.items(), key=lambda item: item[0])
    ]

    errors_by_type: dict[str, int] = {}
    for log in errors:
        error_type = log.error_type or "UnknownError"
        errors_by_type[error_type] = errors_by_type.get(error_type, 0) + 1

    queue_depth = int(request.app.state.ingest_queue.qsize())
    return DashboardSummary(
        window_hours=hours,
        total_requests=total_requests,
        completed_requests=len(completed),
        error_requests=len(errors),
        cancelled_requests=len(cancelled),
        error_rate=round(error_rate, 2),
        avg_latency_ms=round(float(avg_latency), 2) if avg_latency is not None else None,
        p95_latency_ms=round(p95_latency, 2) if p95_latency is not None else None,
        total_tokens=total_tokens,
        queue_depth=queue_depth,
        throughput=throughput_points,
        errors_by_type=errors_by_type,
    )


@app.get("/api/logs/recent", response_model=list[InferenceLogView])
def recent_logs(limit: int = Query(default=30, ge=1, le=200)) -> list[InferenceLogView]:
    with SessionLocal() as db:
        rows = (
            db.execute(select(InferenceLog).order_by(desc(InferenceLog.created_at)).limit(limit))
            .scalars()
            .all()
        )
    return [InferenceLogView.model_validate(row) for row in rows]
