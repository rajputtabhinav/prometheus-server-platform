# Prometheus

Prometheus is a unified server operating platform for monitoring, benchmarking, validation, and safe automation. This repository is a working monorepo across three layers:

- `backend/`: FastAPI controller with structured task orchestration, workflow dispatching, audit events, and a live monitoring websocket.
- `agent/`: Python agent that registers with the controller, streams metrics, polls only whitelisted tasks, and executes structured handlers without raw shell access.
- `frontend/`: React + Tailwind command center with live fleet status, workflow visibility, and task catalog surfaces.

## What Is Implemented

- Safe task catalog with a whitelist-based execution model
- Workflow templates mapped to structured benchmark steps
- Agent registration, heartbeat, metrics ingestion, and task polling APIs
- SQLAlchemy-backed runtime with durable server, metric, run, workflow, and audit persistence
- Alembic-backed schema migrations executed automatically on backend startup
- Persisted auth endpoints for admin, operator, and viewer access with logout and password change
- Persisted alert rules, alert records, notification endpoints, and recurring workflow schedules
- Node detail and run detail APIs with advisories and simple regression summaries
- Celery-backed runtime jobs for schedule dispatch, workflow refresh, stale-run reconciliation, and bounded retry handling
- Operator lifecycle controls for retrying or cancelling runs and cancelling workflows
- Real-time monitoring stream over WebSockets
- Live React dashboard that dispatches real tasks and workflows to connected agents
- Root dev launcher that starts backend and frontend together, with an optional local agent
- Docker Compose topology for backend, frontend, PostgreSQL, Redis, and an example agent
- Celery wiring stub so the queueing path is clear for the next scaling phase

## Important Note

The controller now persists its runtime state through SQLAlchemy, with PostgreSQL configured via `PROMETHEUS_DATABASE_URL`. Schema upgrades run through Alembic on startup when `PROMETHEUS_DATABASE_AUTO_MIGRATE=true`, while repository layering, distributed workers, and production-grade auth hardening remain the next scaling step.

## Repository Layout

```text
.
|-- agent/
|-- backend/
|-- frontend/
|-- docker-compose.yml
`-- README.md
```

## Quick Start

### 1. Full Local Stack

From the repository root:

```bash
npm run dev
```

This starts:

- FastAPI backend on `http://127.0.0.1:8000`
- React frontend on `http://127.0.0.1:5173`

The root launcher disables demo seeding and starts the real web stack.

If you also want a local agent connected automatically, run:

```bash
npm run dev:full
```

### 2. Backend Only

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload
```

Windows PowerShell:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
uvicorn app.main:app --reload
```

### 3. Agent Only

```bash
cd agent
python -m venv .venv
. .venv/bin/activate
pip install -e .
python -m prometheus_agent.main
```

### 4. Frontend Only

```bash
cd frontend
npm install
npm run dev
```

### 5. Full Stack with Docker

```bash
docker compose up --build
```

This now includes:

- API controller
- frontend
- agent
- PostgreSQL
- Redis
- Celery worker
- Celery beat scheduler

## Core API Paths

- `GET /health`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `POST /api/v1/auth/change-password`
- `GET /api/v1/dashboard/summary`
- `POST /api/v1/agents/register`
- `POST /api/v1/agents/{server_id}/heartbeat`
- `POST /api/v1/agents/{server_id}/metrics`
- `POST /api/v1/agents/{server_id}/next-task`
- `POST /api/v1/agents/{server_id}/task-result`
- `POST /api/v1/control/tasks/dispatch`
- `POST /api/v1/control/workflows/dispatch`
- `GET /api/v1/control/runs`
- `GET /api/v1/control/runs/{task_id}`
- `POST /api/v1/control/runs/{task_id}/retry`
- `POST /api/v1/control/runs/{task_id}/cancel`
- `GET /api/v1/control/workflows`
- `POST /api/v1/control/workflows/{workflow_id}/cancel`
- `GET /api/v1/control/nodes/{server_id}`
- `GET /api/v1/control/alerts`
- `GET /api/v1/control/alert-rules`
- `POST /api/v1/control/alert-rules`
- `PATCH /api/v1/control/alerts/{alert_id}`
- `GET /api/v1/control/notifications`
- `POST /api/v1/control/notifications`
- `GET /api/v1/control/schedules`
- `POST /api/v1/control/schedules`
- `PATCH /api/v1/control/schedules/{schedule_id}`
- `GET /api/v1/control/audit`
- `WS /ws/monitoring`
- `WS /ws/live`

## Suggested Next Steps

1. Replace the remaining runtime-heavy orchestration with dedicated service modules and worker-only reconciliation paths.
2. Expand benchmark adapters beyond capability checks into richer `fio`, `iperf3`, GPU, and workload plugins with artifact retention.
3. Introduce CSV/PDF reporting, richer exports, and deeper historical comparison views.
4. Add password reset flows and richer admin UI on top of the persisted auth layer.
5. Add the advisory AI layer and topology-focused inventory surfaces.
