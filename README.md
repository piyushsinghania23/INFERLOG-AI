# InferLog AI

Lightweight inference logging and ingestion system for LLM applications.

This project includes:
- Multi-turn chatbot UI
- Lightweight inference SDK/wrapper that captures metadata and sends it to ingestion
- Ingestion API with validation + parsing + PII redaction
- Database persistence for chat messages and inference logs
- Dashboard endpoints and UI cards for latency/throughput/errors
- Multi-provider support (`gemini`, `openai`, `anthropic`, `mock`)
- Streaming responses, cancel conversation, list/resume conversations
- Docker Compose one-command setup
- Kubernetes manifests for self-hosted deployment baseline

## 1. Architecture Overview

### Core flow
1. User sends a message from the web UI.
2. Backend stores user message and builds a short context window.
3. `ProviderRouter` calls selected LLM provider.
4. `InferenceSDK` emits `started` and final (`completed`/`error`/`cancelled`) events to ingestion API.
5. Ingestion API validates payloads and pushes them onto an internal async queue.
6. Background ingestion worker parses/redacts/stores logs in DB.
7. Assistant response is streamed to UI and persisted as a chat message.
8. Dashboard reads aggregated logs for latency/throughput/error metrics.

### Event-based ingestion
- Ingestion uses an async queue (`app.state.ingest_queue`) so chat path is decoupled from DB writes.
- Queue overflow is explicitly handled with `503`.

## 2. Schema Design

### `conversations`
- `id` (UUID string)
- `title`, `status`
- `provider`, `model`
- `created_at`, `updated_at`

### `chat_messages`
- `id`
- `conversation_id` (FK -> conversations)
- `role` (`user`/`assistant`)
- `content`
- `token_estimate` (fast approximation for observability)
- `created_at`

### `inference_logs`
- `id`, `request_id`
- `conversation_id`, `session_id`
- `event_type` (`started`, `completed`, `error`, `cancelled`)
- `status`, `provider`, `model`
- timing fields (`request_started_at`, `request_ended_at`, `latency_ms`)
- token fields (`prompt_tokens`, `completion_tokens`, `total_tokens`)
- redacted previews (`input_preview`, `output_preview`)
- `error_type`, `error_message`
- `pii_flags`
- `metadata_json`

### Practical tradeoffs
- SQLAlchemy `create_all` instead of migrations for speed.
- Sync ORM in FastAPI for simplicity.
- Streaming to UI is chunked after model completion (still SSE streamed to client).
- SQLite default for local simplicity; Postgres used in Docker/K8s.

## 3. Setup Instructions

## Local (Python)
1. Create and activate virtualenv.
2. Install dependencies:
```bash
pip install -r backend/requirements.txt
```
3. Copy env:
```bash
cp .env.example backend/.env
```
PowerShell alternative:
```powershell
Copy-Item .env.example backend/.env
```
4. Add at least one provider key (`GEMINI_API_KEY`, `OPENAI_API_KEY`, or `ANTHROPIC_API_KEY`), or use `mock`.
5. Run:
```bash
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
from directory:
```bash
cd backend
```
6. Open `http://localhost:8000`.

## Docker Compose (one command)
1. Create `.env` from `.env.example`.
2. Start:
```bash
docker compose up --build
```
3. Open `http://localhost:8000`.

## 4. Demo

### Quick demo path
1. Open app and create a conversation.
2. Send multiple messages to verify short-context multi-turn behavior.
3. Click `Cancel Conversation` while a response is streaming.
4. Select old conversation from left panel to resume.
5. Observe dashboard updates in right panel (latency/errors/throughput/recent logs).

### Notes
- If no external API keys are configured, select provider `mock` for an offline functional demo.
- Real LLM inference is available via `gemini`, `openai`, or `anthropic` when API keys are present.

## 5. API Summary

- `GET /api/health`
- `GET /api/providers`
- `POST /api/conversations`
- `GET /api/conversations`
- `GET /api/conversations/{id}`
- `POST /api/conversations/{id}/messages/stream`
- `POST /api/conversations/{id}/cancel`
- `POST /api/ingest/inference`
- `GET /api/dashboard/summary`
- `GET /api/logs/recent`

## 6. Failure Handling Assumptions

- Provider failures are returned to UI as stream error events and logged as `status=error`.
- Ingestion API accepts and queues logs quickly; queue overflow returns `503`.
- If ingestion post fails, SDK logs warning but does not break chat response path.
- PII redaction happens before log persistence.

## 7. Scaling Considerations

- Move ingestion queue to Kafka/SQS/Rabbit for cross-instance durability.
- Use async DB driver and worker pool for higher write throughput.
- Introduce migrations, partitioned log tables, and retention policies.
- Add distributed tracing and circuit breakers per provider.
- Split chatbot API and ingestion API into separate deployable services.

## 8. Improvements With More Time

- True token-by-token provider streaming for all providers.
- Full auth + tenant isolation.
- Rate limiting and abuse protection.
- Better dashboards (time filters, percentiles over time, per-provider breakdown).
- Automated tests (unit + integration + load).
- Production-grade Kubernetes with secrets manager, autoscaling, and managed Postgres.

## 9. Repository Deliverable

This workspace is ready to be pushed to a GitHub repository as-is.
