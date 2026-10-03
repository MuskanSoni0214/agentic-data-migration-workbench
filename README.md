# Migration Planner & Reconciliation Workbench

Plan, validate, dry-run, approve, execute, reconcile and roll back the migration of one bounded dataset
(1 source, 1 target) into a mock target store. Nothing executes without explicit human approval.

## Architecture
Browser -> FastAPI REST (`backend/main.py`) -> services (`backend/services.py`) -> SQLite (`backend/database.py`).
- `transformations.py`: fixed registry of 12 transformations (all functional, incl. `combine_fields` / `split_field`). No user code is executed.
- `agent.py`: `MigrationPlanningAgent` interface, `MockMigrationPlanningAgent` (default, deterministic), `LLMMigrationPlanningAgent` (stub).
- The mock target store is the `target` table. A primary-key idempotency key `MIG:record:entity` prevents duplicate inserts.

## AI agent and safety controls
- The agent only receives read-only tools: inspect source/target/samples, list/validate transformations and mappings, generate plan. It has no execute, insert or rollback tool.
- Approval needs: no unresolved HIGH risks, no OPEN questions, required targets mapped, explicit confirmation.
- Execution needs: approved plan, a dry run of that same plan version on unchanged samples, and explicit confirmation.
- Approved plans are immutable (DB trigger). Editing creates the next version. The audit log is append-only (DB trigger).
- Sample size is capped (default 50). Rollback only deletes rows created by the selected run and is idempotent.

## Setup
    pip install -r requirements.txt        # runtime; use requirements-dev.txt for tests
    uvicorn backend.main:app --port 8000
Open http://localhost:8000 and API docs at http://localhost:8000/docs.
API example: `curl -X POST localhost:8000/api/demo` loads the 20-record demo (16 valid, 4 invalid); `POST /api/demo/reset` restores it.

## Tests
    python -m pytest tests/unit tests/integration --cov=backend   # needs requirements-dev.txt
    python -m playwright install chromium   # once
    python -m pytest tests/e2e                # drives the real UI + API + SQLite

## Docker
    docker compose up --build

## Frontend
`frontend/index.html` is a no-build single page served by FastAPI. All state comes from the API (`call()`/`api` layer at the top of the script); it keeps only a UI cache and the selected project id in `localStorage`. Refreshing the browser reloads projects, plans, dry runs, runs, reconciliations and history from SQLite. API base URL is the `api-base` meta tag; set `CORS_ALLOWED_ORIGINS` if serving the UI from another origin.

## Status of this build
Implemented and tested: FastAPI, SQLite persistence, API-connected frontend (incl. System Status panel from `GET /api/status`), mock AI agent, all 12 transformations (backend tests + UI selectability test), approval gates, plan versioning, deterministic dry run, quarantine, idempotent execution (verified at DB level), reconciliation, scoped idempotent rollback (second rollback logs one `ROLLBACK_NOOP`), append-only audit log. 39 unit/integration tests and 2 browser E2E tests.

Not implemented: a real LLM provider (`LLMMigrationPlanningAgent` is a stub), authentication (actor is fixed to `demo.user`), React/TypeScript (frontend is plain JavaScript), plan compare of risks/validation rules.

Docker: `Dockerfile` and `docker-compose.yml` are provided but `docker compose build/up` has NOT been run, because Docker was unavailable where this was built. The same install and startup steps were reproduced in a clean virtualenv (runtime requirements only, `backend/` + `frontend/` only, SQLite on a separate data directory): `/`, `/docs` and `/api/status` returned 200. Please run `docker compose config && docker compose up --build` yourself and treat Docker as unverified until you do.
