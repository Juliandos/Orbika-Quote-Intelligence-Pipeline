# Orbika Implementation Phases

This document is the operating roadmap for evolving Orbika Quote Intelligence Pipeline from a file-based local pipeline into a local workshop console backed by PostgreSQL.

The project is coordinated with OpenClaw, but Orbika remains a separate repository:

- OpenClaw repo: `/home/julian95/projects/openclaw-modern`
- Orbika repo: `/home/julian95/projects/Orbika-Quote-Intelligence-Pipeline`

OpenClaw coordinates tasks, evidence, and review. Orbika contains the actual pipeline, app, database, migrations, frontend, backend, and scripts.

## Current Decisions

- The app is local/manual for now.
- The current CLI flow must keep working while the database migration happens.
- PostgreSQL is the target operational database.
- JSON files are still valid as compatibility/source files during migration.
- The final user should not need to inspect folders or JSON files.
- Docker Compose is used locally.
- Python execution uses `uv`.
- FastAPI and Next.js remain the current local app stack.
- No automatic commits from OpenClaw or Codex.
- Secrets must stay outside the repo.
- Orbika PostgreSQL uses host port `5433` mapped to container port `5432`.

## Status Summary

| Phase | Name | Status | OpenClaw Task | Result |
| --- | --- | --- | --- | --- |
| 0 | Current repo diagnosis | Done | `TASK-20260617-002` | Current scripts, outputs, commands, risks, and flow documented by OpenClaw. |
| 1 | Local V1 architecture | Done | `TASK-20260617-003` | Architecture document copied into Orbika. |
| 2 | PostgreSQL data model design | Done | `TASK-20260617-004` | Data model document created in Orbika. |
| 2.1 | PostgreSQL infrastructure and initial migration | Done | `TASK-20260617-009` | Docker Compose DB, Alembic config, and initial schema verified manually. |
| 3 | JSON to PostgreSQL importer | Done | `TASK-20260617-012` | Importer created, real import completed, and idempotency verified. |
| 4 | API reads from PostgreSQL | Done | `TASK-20260617-013` | FastAPI can read dashboard, quote list, and quote detail from PostgreSQL with JSON fallback. |
| 5 | Pipeline persists into PostgreSQL | Done | `TASK-20260618-001` | Runner writes quote, parts and supplier matches to DB. |
| 5.1 | Enriched runner persistence adjustment | Done | `TASK-20260618-002` | Verified manually with HHW977: rerun restored `agentic_reviews` in PostgreSQL and UI. |
| 6 | Reduce generated files | Implemented | `TASK-20260618-003` | Runner defaults to minimal local artifacts, debug outputs moved behind modes, and cleanup helper added. |
| 7 | Workshop UI refinement | Done | Manual implementation | Console UI refined for daily workshop operation with queue filters, stronger detail views, and operational overlays. |
| 8 | Customer preferences and agentic matching improvements | Pending | Not created yet | Add preference memory and better part compatibility reasoning. |
| 9 | RAG and future agents | Pending | Not created yet | Prepare knowledge base and future business assistants. |
| 10 | Local app packaging/startup | Pending | Not created yet | Make the system easier to launch like a normal local app. |

## Completed Work Register

### Phase 0: Current Repo Diagnosis

Status: Done.

OpenClaw task: `TASK-20260617-002`

Purpose:

- Understand the real repository before changing architecture.
- Identify current scripts, outputs, command flow, known errors, and migration risks.

Known outputs identified:

- `local/orbika_incremental/quotes/`
- `local/orbika_incremental/debug/`
- `local/orbika_incremental/snapshots/`
- `local/orbika_incremental/daily/`
- `local/orbika_incremental/agentic_traces/`
- state files under `local/orbika_incremental/`

Acceptance:

- Repo flow documented.
- Commands and generated folders identified.
- Migration risks recorded.

### Phase 1: Local V1 Architecture

Status: Done.

OpenClaw task: `TASK-20260617-003`

Orbika document:

- `docs/architecture/v1-local-postgres-app.md`

Purpose:

- Define how the local app should work for a workshop operator.
- Separate OpenClaw coordination from Orbika implementation.
- Define what should move to PostgreSQL and what can remain as files.
- Define retention policy.

Key decisions:

- PostgreSQL becomes the main operational store in a future phase.
- Execution remains manual for now.
- FastAPI and Next.js stay as the current local app stack.
- The final user should not depend on folders or raw JSON.
- Generated files should be reduced once DB persistence is stable.

Verification:

- Document exists in Orbika.
- It mentions PostgreSQL, FastAPI, Next.js, manual execution, retention, DB vs files, and OpenClaw/Orbika separation.

### Phase 2: PostgreSQL Data Model Design

Status: Done.

OpenClaw task: `TASK-20260617-004`

Orbika document:

- `docs/architecture/postgres-data-model-v1.md`

Purpose:

- Design the first PostgreSQL schema before implementing it.
- Avoid changing runner/backend/frontend before agreeing on the model.

Core tables designed:

- `emails`
- `quotes`
- `vehicles`
- `workshops`
- `parts`
- `supplier_matches`
- `agentic_reviews`
- `customer_preferences`
- `tasks`
- `events`
- `daily_summaries`

Future tables designed:

- `rag_documents`
- `rag_chunks`
- `agent_sessions`
- `agent_messages`
- `business_memory`
- `human_handoffs`

Verification:

- Document exists in Orbika.
- It covers minimum tables, future tables, states, indexes, retention, migration strategy, risks, and acceptance criteria.
- It does not implement PostgreSQL or modify production code.

### Phase 2.1: PostgreSQL Infrastructure And Initial Migration

Status: Done.

OpenClaw task: `TASK-20260617-009`

Orbika files created or updated:

- `.env.example`
- `docker-compose.yml`
- `alembic.ini`
- `migrations/README.md`
- `migrations/env.py`
- `migrations/script.py.mako`
- `migrations/versions/20260617_0001_initial_schema.py`
- `docs/architecture/postgres-local-setup.md`

Purpose:

- Add local PostgreSQL infrastructure.
- Add Alembic migration support.
- Create the initial database schema.

Important local port decision:

- Host port: `5433`
- Container port: `5432`

Reason:

- Port `5432` was already in use locally and should keep working for the existing service.

Manual verification completed from WSL:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline
docker compose config --services
docker compose up -d db
docker compose ps db
docker compose exec db pg_isready -U orbika -d orbika_local
```

Observed result:

- Compose services included `api`, `db`, and `web`.
- `db` became healthy.
- PostgreSQL published as `0.0.0.0:5433->5432/tcp`.
- `pg_isready` returned accepting connections.

Alembic verification completed from WSL:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline
mkdir -p .cache/uv .cache/tmp
export UV_CACHE_DIR="$PWD/.cache/uv"
export TMPDIR="$PWD/.cache/tmp"
export DATABASE_URL="postgresql+psycopg://orbika:orbika_local_dev_password@localhost:5433/orbika_local"
/home/julian95/.local/bin/uv run --with alembic --with psycopg --with psycopg-binary alembic upgrade head
/home/julian95/.local/bin/uv run --with alembic --with psycopg --with psycopg-binary alembic current
```

Observed result:

- Initial migration applied.
- Current revision: `20260617_0001 (head)`.

Notes:

- `.cache/` is local runtime cache and should not be committed.
- OpenClaw had runner limitations with Docker socket and read-only cache, so manual WSL evidence was accepted.

### Phase 3: JSON To PostgreSQL Importer

Status: Done.

OpenClaw task: `TASK-20260617-012`

Goal:

- Import existing quote JSON files into PostgreSQL without changing the current runner.

Expected source:

- `local/orbika_incremental/quotes/*.json`

Expected implementation:

- A local CLI script, for example `tools/import_quotes_to_postgres.py`.
- It should use `DATABASE_URL`.
- It should be idempotent.
- It should tolerate incomplete JSON fields.
- It should report imported, updated, skipped, and failed records.

Suggested verification:

```bash
docker compose ps db
docker compose exec db pg_isready -U orbika -d orbika_local
export DATABASE_URL="postgresql+psycopg://orbika:orbika_local_dev_password@localhost:5433/orbika_local"
/home/julian95/.local/bin/uv run --with psycopg --with sqlalchemy python tools/import_quotes_to_postgres.py --limit 1 --dry-run
/home/julian95/.local/bin/uv run --with psycopg --with sqlalchemy python tools/import_quotes_to_postgres.py --limit 1
```

Verification completed:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline
export DATABASE_URL="postgresql+psycopg://orbika:orbika_local_dev_password@localhost:5433/orbika_local"
export UV_CACHE_DIR="$PWD/.cache/uv"
export TMPDIR="$PWD/.cache/tmp"
/home/julian95/.local/bin/uv run --with psycopg --with psycopg-binary python tools/import_quotes_to_postgres.py
```

### Phase 5.1: Enriched Runner Persistence Adjustment

Status: Done.

OpenClaw task: `TASK-20260618-002`

Purpose:

- Ensure the incremental runner persists `agentic_supplier_matching` to PostgreSQL in the same pass.
- Verify that UI-visible agentic review can be rebuilt from a fresh runner pass.

Verification completed:

- Quote `HHW977` (`quote_key = db2e4ac3c45513d17babbf37`) was deleted from PostgreSQL.
- The runner was re-executed for `2026-06-05` with isolated state/quotes/snapshots/daily paths.
- After rerun, PostgreSQL contained:
  - `32` parts
  - `69` supplier matches
  - `32` agentic reviews
- The quote also became visible again in the UI with agentic review populated.

### Phase 6: Reduce Generated Files

Status: Implemented.

OpenClaw task: `TASK-20260618-003`

Purpose:

- Reduce local file sprawl now that PostgreSQL is the operational source of truth.
- Keep compatibility and resume behavior without making the operator depend on folders.

Implementation:

- The incremental runner now supports `--file-output-mode`:
  - `minimal` (default): `state.json`, `quotes/`, `daily/`
  - `standard`: `minimal` + `agentic_traces/`
  - `debug`: `standard` + `snapshots/`
- Explicit `--snapshot-dir` and `--agentic-trace-dir` still override the mode.
- Added `tools/cleanup_incremental_outputs.py` with dry-run by default.

Retention policy established:

- `state.json`: always keep
- `quotes/`: keep as compatibility/debug minimum
- `daily/`: regenerable
- `agentic_traces/`: debug retention target of 7 days
- `snapshots/`: debug retention target of 7 days
- `debug/`: debug retention target of 7 days
- `check-*`, `backfill-*`, `phase*`, `retest-*`: experimental artifacts, cleanup candidate after 7 days

Verification:

- Runner argument defaults updated and covered by tests.
- Cleanup helper covered by unit tests.
- No existing CLI flow was removed; debug-heavy outputs remain available explicitly.

## Pending Phases

First real import result:

- `imported=48`
- `updated=0`
- `skipped=0`
- `failed=0`
- `emails=48`
- `quotes=48`
- `vehicles=31`
- `workshops=31`
- `parts=144`
- `supplier_matches=279`
- `agentic_reviews=144`

Second real import result for idempotency:

- `imported=0`
- `updated=48`
- `skipped=0`
- `failed=0`

Final PostgreSQL counts:

- `emails=48`
- `quotes=48`
- `vehicles=31`
- `workshops=31`
- `parts=144`
- `supplier_matches=279`
- `agentic_reviews=144`

Duplicate check:

- `quote_key` duplicates: `0`

Notes:

- The current runner, frontend, backend API, and source JSON files were not changed.
- `.cache/` and `tools/__pycache__/` are local runtime artifacts and should not be committed.

Acceptance:

- At least one real quote imports successfully.
- Running the importer twice does not duplicate records.
- Current JSON flow still works.

### Phase 4: API Reads From PostgreSQL

Status: Done.

OpenClaw task: `TASK-20260617-013`

Goal:

- Move the FastAPI read side from JSON files to PostgreSQL gradually.

Suggested approach:

- Add DB repository/query layer.
- Add feature flag or configuration to choose JSON vs DB reads.
- Keep existing JSON endpoints working until DB is trusted.

Implementation:

- Added `apps/api/orbika_console_api/postgres_store.py`.
- Added `ORBIKA_API_STORE=json|postgres`.
- Kept `quote_store.py` as JSON fallback.
- Kept the existing API route shapes for dashboard, quote list, and quote detail.
- Did not change runner, supplier matching, agentic review, frontend behavior, or source JSON files.

Activation:

```bash
export DATABASE_URL="postgresql+psycopg://orbika:orbika_local_dev_password@localhost:5433/orbika_local"
export ORBIKA_API_STORE=postgres
uv run uvicorn --app-dir apps/api orbika_console_api.main:app --reload --host 0.0.0.0 --port 8001
```

Use JSON fallback:

```bash
export ORBIKA_API_STORE=json
```

Verification:

- Dashboard counts match imported DB data.
- Quote list loads from DB.
- Quote detail loads from DB.
- Existing frontend remains usable.

Verification completed with FastAPI `TestClient` in Postgres mode:

- `GET /api/health`: `{"ok": true, "store": "postgres"}`
- `GET /api/dashboard`: `quotes_total=48`, `loaded_quotes=29`, `failed_quotes=5`, `partial_quotes=14`
- `GET /api/quotes`: `48` quotes
- `GET /api/quotes/04e4f0e8ec60506f1cbbb931`: quote key `04e4f0e8ec60506f1cbbb931`, aviso `419451`, `1` part, `1` supplier matching part, `1` agentic part

Acceptance:

- UI can show quotes from PostgreSQL.
- JSON fallback remains available during transition.

### Phase 5: Pipeline Persists Into PostgreSQL

Status: Done with Phase 5.1 adjustment implemented.

OpenClaw tasks:

- `TASK-20260618-001`
- `TASK-20260618-002`

Goal:

- Make the incremental runner write operational records to PostgreSQL.
- Ensure the enriched runner output reaches PostgreSQL consistently.

Suggested approach:

- Keep JSON output initially.
- Add DB persistence after each successful extraction/matching step.
- Record task/events for UI activity.

Implemented behavior:

- The incremental runner still writes compact quote JSON files for compatibility.
- After Orbika extraction, it runs supplier matching.
- After supplier matching, it now runs the existing agentic supplier review in the
  same quote processing pass by default.
- The runner writes `agentic_supplier_matching` into the quote JSON and writes a
  local trace under `local/orbika_incremental/agentic_traces/`.
- PostgreSQL persistence runs after the enriched JSON is written, so
  `agentic_reviews` rows are inserted when `agentic_supplier_matching.parts`
  exists.
- The compatibility flag `--skip-agentic-review` intentionally disables this
  final review for diagnostics or old-style runs.

Phase 5.1 finding:

- PostgreSQL persistence was already capable of inserting `agentic_reviews`.
- The inconsistency observed with HHW977 came from the incremental runner path:
  it persisted immediately after supplier matching and before agentic review.
- Therefore, a Gmail reproceso could restore `quotes`, `parts` and
  `supplier_matches` while leaving `agentic_reviews=0`.
- Agentic review is now part of the automatic runner flow unless explicitly
  skipped.

Verification:

- New quote email creates DB rows.
- Existing JSON files are still produced until Phase 6 decides otherwise.
- Runner remains restart-safe.
- Unit coverage confirms runner output can be enriched with
  `agentic_supplier_matching` and trace files before persistence.
- Sandbox limitation for `TASK-20260618-002`: Docker socket access was denied and
  the local PostgreSQL connection was unavailable, so Gmail reproceso and live DB
  verification must be repeated from a normal WSL shell.

Acceptance:

- New quotes appear in DB without running importer.
- No duplicate quote rows after retries.
- Agentic review is persisted automatically when review runs and matching output
  exists.

### Phase 6: Reduce Generated Files

Status: Pending.

Goal:

- Stop overwhelming the user with generated folders and huge JSON outputs.

Suggested approach:

- Keep compact final quote JSON only if still useful.
- Keep one example fixture for documentation/testing.
- Disable snapshots by default.
- Keep traces/logs with retention.

Retention target:

- Quotes in DB: last 90 days by default.
- Logs/events: 30 days.
- Snapshots/debug artifacts: 7 days only if explicitly enabled.
- Examples/fixtures: keep only curated samples.

Acceptance:

- User does not need to inspect `local/` folders.
- Generated outputs are compact and purposeful.

### Phase 7: Workshop UI Refinement

Status: Done.

Implementation mode:

- Implemented directly in Orbika without a separate OpenClaw execution packet.

Goal:

- Make the console practical for non-technical workshop use.

Implemented improvements:

- Reworked the quote queue into a larger operational rail with live counters, search, and quick filters.
- Improved the selected quote header with stronger hierarchy and at-a-glance operational chips.
- Reorganized the detail view into clearer overview, parts, matches, and agentic work surfaces.
- Added more useful operational overlays for pipeline status, activity, and runner actions.
- Improved empty states and visual spacing so the operator can review quotes without reading raw JSON.

Files updated:

- `apps/web/app/page.tsx`

Verification completed:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline/apps/web
npm run build
```

Observed result:

- Next.js production build completed successfully.
- TypeScript and lint validation passed during build.

Acceptance:

- Operator can work from UI without terminal or JSON files for the main review flow.
- Important quote and match information fits on screen with clearer scroll behavior and overlays.

### Phase 8: Customer Preferences And Agentic Matching Improvements

Status: Pending.

Goal:

- Improve matching usefulness with customer and workshop-specific knowledge.

Planned capabilities:

- Customer preference table.
- Short actionable agentic comments.
- Compatibility warnings such as year/model/version differences.
- Ranking that explains why a part may or may not work.

Acceptance:

- Agentic review gives concise top options.
- Comments help the user decide faster.
- Preferences can influence future rankings.

### Phase 9: RAG And Future Agents

Status: Pending.

Goal:

- Prepare the knowledge layer for future agentic assistants.

Future assistants:

- Public/customer service assistant with FAQ, scheduling, and human handoff.
- Internal business assistant for the workshop owner.
- Technical knowledge assistant for parts, accessories, compatibility, and quoting.

Suggested search terms for future knowledge gathering:

- automotive aftermarket parts compatibility
- collision repair estimating parts terminology
- auto body replacement parts catalog standards
- vehicle trim compatibility guide
- OEM vs aftermarket auto parts compatibility
- Colombian automotive spare parts catalog
- accesorios automotrices compatibilidad modelos anos
- autopartes carroceria homologacion Colombia
- partes de colision catalogo tecnico
- bumper fender headlamp compatibility guide

Acceptance:

- RAG documents and chunks have a future schema.
- No RAG implementation is required until DB import and API migration are stable.

### Phase 10: Local App Packaging And Startup

Status: Pending.

Goal:

- Make the app easy to start for a non-technical Windows user.

Possible future direction:

- Keep WSL/Docker internally.
- Provide a launcher script or desktop shortcut.
- Start backend, frontend, DB, and runner from one controlled entry point.

Acceptance:

- The operator can start the system without typing multiple commands.
- Failures are visible and understandable.

## Evidence Rules

Each phase should record:

- OpenClaw task ID.
- Files created or modified.
- Commands executed.
- Verification results.
- Known limitations.
- Whether commits were intentionally not made.

Do not mark a phase done unless:

- The main deliverable exists.
- The verification passed or a human-approved external verification is recorded.
- The current CLI flow is not broken unless the phase explicitly changes it.

## Next Recommended Task

Create OpenClaw task for Phase 3:

- Name: `Orbika Phase 3 JSON to PostgreSQL importer`
- Scope: import existing quote JSON files into PostgreSQL.
- Restriction: do not modify runner/frontend/backend behavior yet.
- Verification: import one quote, rerun importer, confirm no duplication.

