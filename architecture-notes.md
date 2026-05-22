# Architecture Notes

## Ingestion Flow
1. Chat endpoint uses `InferenceSDK` to emit a `started` event before provider call.
2. After inference finishes (or fails/cancels), SDK emits final event with latency, usage, and previews.
3. Ingestion API validates payload with Pydantic (`InferenceLogPayload`).
4. Valid logs are queued (`asyncio.Queue`) to avoid blocking chat request path.
5. Background worker consumes queue and persists normalized records into `inference_logs`.
6. PII redaction occurs during persistence and `pii_flags` are stored for audits.

## Logging Strategy
- Request lifecycle events:
  - `started`
  - `completed`
  - `cancelled`
  - `error`
- Captured metadata:
  - provider/model/session/request IDs
  - timing + latency
  - token usage
  - redacted input/output previews
  - status + error metadata
  - custom metadata (`context_messages`, `assistant_message_id`)

## Scaling Considerations
- Replace in-memory queue with managed broker for durability.
- Deploy ingestion workers independently of chat service.
- Use pooled async DB writes and log table partitioning.
- Add backpressure monitoring (queue depth alarms).
- Introduce per-provider concurrency controls and retries.

## Failure Handling Assumptions
- Provider/API errors are non-fatal to server and surfaced to user stream.
- SDK ingestion failures do not fail user-facing chat; they degrade observability only.
- Queue overflow returns `503` from ingestion endpoint (explicit signal).
- Cancel requests are best-effort: current implementation cancels streamed output path.
