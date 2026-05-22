from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import InferenceLog
from ..schemas import InferenceLogPayload
from .pii import redact_pii


def persist_inference_log(db: Session, payload: InferenceLogPayload) -> InferenceLog:
    input_preview, input_flags = redact_pii(payload.input_preview)
    output_preview, output_flags = redact_pii(payload.output_preview)
    pii_flags = sorted(set(input_flags + output_flags))

    record = InferenceLog(
        request_id=payload.request_id,
        conversation_id=payload.conversation_id,
        session_id=payload.session_id,
        event_type=payload.event_type,
        status=payload.status,
        provider=payload.provider,
        model=payload.model,
        request_started_at=payload.request_started_at,
        request_ended_at=payload.request_ended_at,
        latency_ms=payload.latency_ms,
        prompt_tokens=payload.prompt_tokens,
        completion_tokens=payload.completion_tokens,
        total_tokens=payload.total_tokens,
        input_preview=input_preview,
        output_preview=output_preview,
        error_type=payload.error_type,
        error_message=payload.error_message,
        pii_flags=pii_flags,
        metadata_json=payload.metadata or {},
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
