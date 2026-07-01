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
| 8 | Agentic matching baseline | Done | Manual implementation | Preference-aware ranking, compact compatibility warnings, and concise agentic notes are implemented. |
| 8.1 | Technical compatibility hardening | Implemented pending owner review | Manual implementation | Regression set, compatibility matrix, deterministic rules, API/UI evidence labels, and tests are implemented; owner review still required. |
| 8.2 | Controlled workshop preferences | Optional after 8.1 review | Not created yet | Add a small, auditable preference editor only if owner review proves it is worth the operational complexity. |
| 9 | Technical RAG for part selection with local embeddings and pgvector | In progress | Manual implementation | Text RAG schema is already live; the local embedding provider is now implemented in code with `sentence-transformers`, `pgvector` migration, hybrid search scaffolding, and embedding-aware ingestion pending live validation and corpus reindex. |
| 10 | End-to-end verification and hardening | Pending | Not created yet | Recover and prove the complete operational flow, including the waiting runner and every UI action. |
| 11 | Simple local operation and startup | In progress | Manual implementation | Windows launcher, preflight, stop flow, maintenance/reporting, weekly maintenance scheduler, weekly provider refresh, and launcher supervision are implemented; final Windows operator rehearsal and packaging guidance remain pending. |

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

## Recent And Remaining Phases

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

### Phase 7: Workshop UI Refinement

Status: Done.

Purpose:

- Make the console practical for non-technical workshop use.

Delivered:

- A larger quote queue with counters, search, and quick filters.
- Stronger selected-quote hierarchy and operational status.
- Structured summary, parts, matches, and agentic views.
- Pipeline, activity, and runner overlays.
- Usable scrolling and empty states without raw JSON.

Verification:

    cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline/apps/web
    npm run build

Acceptance achieved:

- The principal review flow is usable without a terminal or raw JSON.
- The production frontend build passes.

## Final Execution Plan

Execute the remaining phases in order. A later phase must not hide a failed verification from an earlier phase. Split implementation into small tasks with explicit evidence and preserve the current CLI unless a phase explicitly changes it.

### Phase 8: Agentic Matching Baseline

Status: Done.

#### Purpose

Establish a compact technical review layer over deterministic supplier matching. It helps the owner compare plausible products; it does not replace extraction, matching, or the owner's final decision.

#### Scope

Included:

- Load preferences from quote payload or PostgreSQL.
- Apply provider, brand, exact-reference, year-tolerance, and option-limit preferences.
- Detect visible side, position, and year conflicts.
- Reject clear side or position conflicts.
- Return at most three relevant agentic options.
- Expose short risk and preference notes through API and UI.

Excluded:

- Public FAQ or customer-service chatbot.
- General workshop assistant.
- PDF ingestion or vector retrieval.
- Automatic purchasing or quote submission.

#### Deliverables

- tools/customer_preference_store.py
- Preference-aware supplier matcher.
- Compact agentic reviewer.
- API and UI support for risk and preference notes.
- Focused unit tests.

#### Implementation Steps Completed

1. Normalize preferences for the current quote.
2. Run deterministic matching as candidate generator.
3. Apply preferences only to technically plausible options.
4. Reject visible hard side and position conflicts.
5. Penalize and display visible year conflicts.
6. Limit candidates sent to agentic review.
7. Persist and render compact operational results.

#### Technical Verification

    cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline
    python3 -m unittest tests.test_supplier_quote_matcher tests.test_agentic_match_reviewer
    cd apps/web
    npm run build

Expected:

- Focused tests and frontend build pass.
- Side and position conflicts are rejected.
- Year conflicts remain visible.
- Compact fields render safely.

#### Operational/Human Verification

1. Select a known quote with several supplier options.
2. Compare the top three against deterministic matches.
3. Confirm notes are understandable without JSON.
4. Confirm preferences change ranking only when compatibility remains plausible.
5. Confirm the owner can reject any recommendation.

#### Acceptance Criteria

- No more than three meaningful options per part.
- Clear incompatibilities are not top recommendations.
- Comments are short, factual, and actionable.
- CLI and PostgreSQL persistence remain functional.
- The owner remains final decision-maker.

#### Risks

- Supplier titles omit important evidence.
- Preferences can be mistaken for technical facts.
- Short notes can hide uncertainty.

#### If Verification Fails

- Stop before Phase 8.1.
- Add the failing quote as a sanitized fixture.
- Locate the earliest faulty layer: extraction, matching, preference, agentic review, persistence, API, or UI.
- Fix that layer and repeat technical and human checks.
- Never mask a deterministic error with a prompt-only change.

### Phase 8.1: Technical Compatibility Hardening

Status: Implemented pending owner review.

#### Purpose

Increase selection precision with structured compatibility checks before agentic ranking. Missing evidence must remain unknown instead of becoming a model guess.

#### Scope

Included:

- Part/reference number.
- Make, model, year range, generation, trim, and body style when present.
- Side, position, color, finish, dimensions, presentation, and kit-versus-unit when present.
- Hard conflicts, soft warnings, and unknown states.
- Provider-specific parsing only when stable examples justify it.
- Compact evidence across matching, agentic review, persistence, API, and UI.

Excluded:

- RAG retrieval.
- Conversational interfaces.
- Claims based only on model memory.
- Automatic acceptance of an option.

#### Deliverables

- Compatibility vocabulary and severity matrix.
- Curated regression set of 10 to 20 real, sanitized cases.
- Normalized compatibility evidence.
- Deterministic rejection and penalty rules.
- UI labels for compatible, warning, incompatible, and insufficient information.
- Tests for every rule and missing-data behavior.

#### Implementation Steps

1. Build the regression set before scoring changes.
   - Include exact matches, close alternatives, wrong year, wrong side, wrong position, kit/unit, and incomplete titles.
   - Record the owner's expected result.

2. Define the evidence vocabulary.
   - Specify normalized representation and source for each signal.
   - Classify each as hard, soft, or informational.
   - Define unknown explicitly.

Current baseline created in this slice:

- `tests/fixtures/phase8_1_regression_cases.json`
- `tests/test_phase8_1_regression.py`
- `docs/architecture/phase8-1-compatibility-matrix.md`

These artifacts freeze the first executable regression set and the compatibility vocabulary before scoring changes.

3. Add extraction helpers.
   - Parse only visible data.
   - Preserve source text for audit.
   - Require at least three stable examples before provider-specific parsing.

4. Apply compatibility gates.
   - Reject contradictory side, position, or exact-reference evidence when explicit.
   - Penalize uncertain year, generation, or trim differences unless incompatibility is proven.
   - Never allow preferences to override hard conflicts.

5. Rebalance ranking.
   - Keep the current matcher as candidate generator.
   - Rank exact and strongly compatible options first.
   - Keep the final agentic output at one to three options.

6. Extend persistence only if necessary.
   - Inspect current schema first.
   - Reuse suitable evidence/JSON fields when auditable.
   - If schema changes are required, add a new Alembic migration and test it on a disposable DB.

7. Improve UI evidence.
   - Show decisive facts, not internal scoring noise.
   - Place warnings beside the affected option.
   - Preserve provider links.

#### Technical Verification

    cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline
    python3 -m unittest tests.test_supplier_quote_matcher tests.test_agentic_match_reviewer
    docker compose ps db
    docker compose exec db pg_isready -U orbika -d orbika_local
    curl -s http://localhost:8001/api/quotes/<quote_key> | jq .

Verify:

- Every curated hard conflict is rejected.
- Unknown data remains unknown.
- Valid legacy cases retain candidates.
- Reprocessing creates no duplicates.
- DB, API, and UI show the same decisive evidence.
- Existing CLI arguments work.

#### Operational/Human Verification

1. Let the owner review the regression set without seeing expected results.
2. Record whether the top option is usable and why.
3. Classify false positives, false negatives, and unclear language.
4. Keep only understandable and repeatable rules.
5. Review provider-specific exceptions with the owner.

#### Acceptance Criteria

- All curated hard conflicts are rejected.
- At least 90 percent of curated cases place an owner-approved option in the top three; record baseline and result.
- Missing information requests manual validation.
- Preferences cannot override hard compatibility.
- CLI, persistence, API, and frontend build do not regress.
- The owner approves warning language.

#### Risks

- Strict rules can remove useful alternatives.
- Supplier naming creates parsing errors.
- Generation and trim may be absent.
- Too much evidence can clutter the UI.

#### If Verification Fails

- Disable or revert only the failing rule.
- Add the case to regression fixtures before changing code.
- Downgrade an uncertain hard rejection to a warning.
- Do not tune thresholds from one quote.
- Repeat owner review after tests pass.

### Phase 8.2: Controlled Workshop Preferences

Status: Optional after Phase 8.1 owner review.

#### Purpose

Let the owner maintain a small set of operational preferences without weakening technical safety.

#### Activation Rule

Do not start this phase automatically after Phase 8.1. Start it only if the owner review of Phase 8.1 shows that a controlled preference layer would clearly improve real quote decisions more than it increases maintenance burden.

#### Scope

Included:

- Approximately 10 to 20 active preferences.
- General and limited part/provider-specific rules.
- Preferred or avoided provider/brand.
- Exact-reference preference, year tolerance, and option limit.
- UI create, edit, enable/disable, and delete.
- Audit fields and deterministic precedence.

Excluded:

- Free-form prompt editing.
- Unlimited rules.
- Preferences overriding hard incompatibilities.
- Silent behavioral learning.
- Automation outside quote review.

#### Deliverables

- Reviewed preference schema using customer_preferences where possible.
- Alembic migration only if required.
- Validated FastAPI CRUD endpoints.
- Simple preference form with active count and enabled state.
- Runtime integration and traceable applied reasons.
- API, matcher, reviewer, and UI tests.
- Short operator guide.

#### Implementation Steps

1. Inventory current table, loader, matcher inputs, and API support.
2. Define a small enumerated preference catalog and maximum of 20 active rules.
3. Define precedence:
   - Part-specific beats general for the same type.
   - Explicit priority resolves equal scope.
   - Hard compatibility always wins.
   - Conflicting active rules are rejected.
4. Reuse the table when possible; migrate only missing required fields.
5. Add server-side CRUD validation and clear limit/conflict errors.
6. Add a form-based UI, not raw JSON or a text prompt.
7. Load active preferences in matching and agentic review.
8. Record which preference affected a recommendation.
9. Seed only owner-confirmed preferences and test on controlled fixtures.

#### Technical Verification

- Migration succeeds if needed.
- CRUD tests cover valid, invalid, conflict, disabled, delete, and over-limit cases.
- The 21st active rule is rejected when the limit is 20.
- Disabled rules have no effect.
- Hard conflicts beat favorite provider/brand.
- Reprocessing remains idempotent.
- Frontend build passes.

#### Operational/Human Verification

1. Owner creates one general rule.
2. Owner creates one part-specific rule.
3. UI wording is confirmed.
4. A known quote is compared before and after.
5. Disabling the rule restores baseline behavior.
6. Owner confirms a preference is not a compatibility certificate.

#### Acceptance Criteria

- Preferences are managed without files or SQL.
- Active count stays within the configured limit.
- Applied rules are traceable.
- Hard warnings cannot be suppressed.
- Invalid/conflicting rules show a clear error.
- API, CLI, runner, DB, and UI remain compatible.

#### Risks

- Excess exceptions make ranking unpredictable.
- Favorite provider may be treated as technical proof.
- Free text can become a hidden prompt.
- Concurrent edits can overwrite state.

#### If Verification Fails

- Disable editing and retain read-only display.
- Restore the last validated bundle.
- Fix API validation before UI behavior.
- Remove or narrow conflicting rule types.
- Keep Phase 8.2 optional and continue with Phase 9 if the technical baseline from Phase 8.1 is already strong enough.

### Phase 9: Technical RAG For Part Selection

Status: Implemented pending corpus validation.

#### Purpose

Add curated technical retrieval as evidence for agentic review. RAG complements Phase 8.1 directly and may optionally consume Phase 8.2 preferences later if that phase is ever enabled. It is not restricted to ambiguous cases and is not a FAQ product.

#### Scope

Included:

- Curated technical PDFs and trusted references.
- Ingestion, chunking, embeddings, retrieval, provenance, and versions.
- Retrieval per reviewed part when relevant material exists.
- Evidence that confirms, warns, or rejects a candidate.
- Internal source citation.
- Offline ingestion, bounded retrieval, and bounded candidates for cost control.

Excluded:

- Public or customer-service chatbot.
- Unrestricted production web search.
- Retrieved text overriding explicit hard evidence.
- Purchase, payment, or quote submission.
- General business assistant.

#### Deliverables

- Source acceptance policy and approved starter corpus.
- PostgreSQL document/chunk persistence with migration.
- Canonical local source folder for the technical corpus before ingestion.
- Idempotent ingestion CLI.
- Retrieval service integrated with agentic review.
- Input contract separating facts, deterministic evidence, preferences, and RAG.
- Compact cited output and non-RAG fallback.
- Evaluation fixtures and latency/cost report.

#### Document Intake Pause And Local Folder

Before coding the ingestion step, pause the implementation and prepare the starter corpus manually.

Store the technical PDFs here:

- `knowledge/rag_sources/` for all approved technical source documents that will feed the RAG pipeline.

If later you need to quarantine or reject files, that can be handled with metadata or a future cleanup pass, but the initial implementation should assume a single curated folder.

Do not ingest directly from ad hoc desktop folders or downloads. Move files into the repo structure first so the corpus is reviewable, reproducible, and easy to audit.

#### When To Pause For Documents

Pause immediately after the Phase 9 scaffolding step, before embeddings or ingestion are implemented, if the technical PDFs are not yet ready in `knowledge/rag_sources/`. At that moment:

1. Ensure `knowledge/rag_sources/` exists.
2. Collect an initial small corpus of trusted PDFs.
3. Normalize filenames so they are stable and descriptive.
4. Resume coding only after there are enough approved documents to test retrieval on real part-selection scenarios.

#### Search Terms For Technical PDFs

Combine with filetype:pdf, make/model, country, or part family:

- automotive aftermarket parts compatibility
- collision repair parts terminology
- OEM aftermarket homologated parts guide
- vehicle body parts compatibility catalog
- bumper fender headlamp application guide
- automotive lighting fitment guide
- vehicle trim generation compatibility manual
- autopartes carroceria catalogo tecnico
- repuestos homologados Colombia ficha tecnica
- accesorios automotrices compatibilidad modelos anos
- manual reparacion carroceria marca modelo
- catalogo aplicaciones autopartes marca modelo

Prefer manufacturer catalogs, standards bodies, official repair information, and established technical publishers.

#### Implementation Steps

1. Define evaluation cases and baseline results before choosing technology.
2. Ensure `knowledge/rag_sources/` exists and contains the curated starter corpus.
3. Pause and collect the initial approved corpus if it does not exist yet.
4. Record title, publisher, version, source, license, checksum, language, and approval for every document, either in the database or in a manifest created by the ingestion step.
5. Inspect planned rag_documents/rag_chunks against actual schema.
6. Select a local PostgreSQL-compatible embedding strategy and create a new migration.
7. Build idempotent text extraction, cleanup, chunking, page references, embeddings, and import report.
8. Query using normalized part/vehicle facts, not the whole email.
9. Retrieve a bounded three to five chunks with metadata filters and a relevance threshold.
10. Run deterministic compatibility first and optional preferences second if Phase 8.2 exists.
11. Provide RAG as separate cited evidence that cannot override hard conflicts.
12. Use retrieval evidence to refine labels and comments when it adds real specificity.
13. Show a short reason, source, and unresolved risk without dumping chunks.
14. Continue with Phase 8 behavior if RAG, vector storage, or the model fails.
15. Cache safe retrieval signatures and record latency/model usage.

#### Technical Verification

- Migration upgrade/downgrade passes on a disposable DB.
- Re-ingestion creates no duplicate active chunks.
- Evaluation queries return expected source/page.
- Irrelevant queries return no evidence above threshold.
- Output cites only supplied retrieval results.
- Disabling RAG restores validated Phase 8 behavior.
- Retrieval/model failure does not stop email processing or DB persistence.
- API/UI expose neither vectors nor oversized chunks.

#### Operational/Human Verification

1. Compare baseline and RAG-assisted answers blind.
2. Mark evidence as useful, neutral, or confusing.
3. Reject untrusted sources or wording.
4. Confirm citations are inspectable without slowing normal work.
5. Owner or experienced professional approves the starter corpus before ingestion.
6. Owner confirms that the improved labels/comments help choose the right part faster, not just look smarter.

#### Acceptance Criteria

- Relevant corpus evidence is cited during review.
- Evaluation records improvement over baseline with no newly accepted hard conflicts.
- Unsupported claims are not facts.
- Base pipeline works with RAG disabled/unavailable.
- Output remains compact.
- No FAQ/chat branch is introduced.

#### Risks

- Outdated sources worsen recommendations.
- Similar text may be technically unrelated.
- Licensing/provenance can be unclear.
- Model changes alter retrieval.
- Latency/cost may outweigh value.

#### If Verification Fails

- Disable RAG and preserve Phase 8 fallback.
- Quarantine bad source/chunk.
- Adjust source quality, chunking, metadata, or threshold before prompt tuning.
- Add the failure to evaluation fixtures.
- Do not start Phase 10 until RAG cannot block the base pipeline.

#### Phase 9 Extension: Embeddings And pgvector Upgrade

Status: In progress. Local embedding provider and vector search scaffolding are implemented in code; pending live corpus re-ingestion and validation.

Purpose:

- Evolve the current text-based RAG into a hybrid retrieval layer that combines lexical search with semantic embeddings.
- Improve recall when the quote wording and the technical document wording are different but refer to the same part or compatibility rule.
- Produce stronger technical evidence for the agentic reviewer so the final recommendation is more precise and easier for the workshop owner to trust.

Current state already available:

- `rag_documents` and `rag_chunks` exist in PostgreSQL.
- PDF ingestion into `knowledge/rag_sources` is already working.
- Text search is already returning chunked evidence from the stored corpus.
- Agentic review can already consume compact evidence from the existing RAG layer.
- `docker-compose.yml` now uses `pgvector/pgvector:pg16` so the local DB can host vector storage and similarity search.
- `tools/rag_knowledge_base.py` now supports local embeddings by default, vector storage, and hybrid search with text fallback. OpenAI embeddings remain an optional fallback path only if explicitly requested.

New scope to add:

- Keep PostgreSQL `pgvector` enabled for chunk similarity search.
- Keep an embedding column for chunk vectors at the selected local model size.
- Generate embeddings during ingestion and on document refresh.
- Support hybrid retrieval:
  - lexical match by PostgreSQL text search
  - semantic match by vector similarity
  - merged or reranked final evidence list
- Surface in the review output whether evidence came from text retrieval, vector retrieval, or both.

Expected deliverables:

- New Alembic migration for `pgvector` support and chunk embedding storage. Implemented as `migrations/versions/20260625_0003_rag_pgvector_embeddings.py`.
- Updated RAG ingestion command that can:
  - ingest documents
  - compute embeddings
  - re-embed changed chunks only
- Retrieval helper that supports hybrid search.
- Agentic review updates so recommendations can cite vector-backed evidence.
- Documentation updates for required environment variables and verification steps.

#### WSL Environment Variables

Keep using normal WSL shell exports for this phase. Do not require `.env` yet.

Example session values before running ingestion or search:

- `export DATABASE_URL="postgresql+psycopg://orbika:orbika_local_dev_password@localhost:5433/orbika_local"`
- `export RAG_EMBEDDING_PROVIDER=local`
- `export RAG_EMBEDDING_MODEL=intfloat/multilingual-e5-small`
- `export RAG_EMBEDDING_DIMENSIONS=384`
- `export RAG_VECTOR_SEARCH_ENABLED=1`

OpenAI embedding variables remain optional and only matter if a future fallback is explicitly requested.

Example WSL commands:

- Ingest the corpus locally:
  - `PYTHONPATH=. uv run --with pypdf --with sentence-transformers --with torch --with "psycopg[binary]" python tools/rag_knowledge_base.py ingest --source-dir knowledge/rag_sources`
- Search the indexed corpus locally:
  - `PYTHONPATH=. uv run --with sentence-transformers --with torch --with "psycopg[binary]" python tools/rag_knowledge_base.py search --query "guardabarro izquierdo mazda cx30 2022" --limit 5`

Implementation steps:

1. Install and enable `pgvector` in the local PostgreSQL container.
2. Add a migration that:
   - creates the extension if needed
   - adds an embedding column to `rag_chunks`
   - creates the required vector index
3. Define the embedding model configuration through environment variables so it can be changed without code rewrites.
4. Update the RAG ingestion tool to:
   - compute embeddings for each normalized chunk
   - avoid recomputing embeddings for unchanged content
   - store embedding metadata such as model name and version
5. Add hybrid retrieval logic:
   - text search first-pass
   - vector similarity first-pass
   - merged scoring or reranking
6. Update agentic review prompts and evidence assembly so the reviewer can distinguish:
   - exact lexical evidence
   - semantic technical evidence
   - low-confidence evidence that still needs manual validation
7. Keep the current text mode as fallback in case embeddings are temporarily unavailable.

Technical verification:

- Confirm `pgvector` is installed and enabled in the local DB.
- Confirm chunks now store embeddings in addition to text fields.
- Run ingestion on the existing corpus and verify:
  - documents imported
  - chunks embedded
  - re-ingest skips unchanged chunks correctly
- Run comparison searches where plain text previously returned weak or empty results and verify hybrid retrieval returns better evidence.
- Verify the agentic review output now includes visible evidence of vector-backed or hybrid-backed reasoning when applicable.

Operational verification:

- Select 5 to 10 real quote parts where wording is noisy, abbreviated, or commercially phrased.
- Compare before vs after:
  - text-only retrieval quality
  - hybrid retrieval quality
  - usefulness of the final recommendation for the workshop owner
- Confirm the added precision is worth the extra cost and complexity.

Acceptance criteria:

- The project can ingest and search technical PDFs using both text and vector retrieval.
- Agentic review shows stronger and more specific evidence for hard matches.
- The pipeline still works if vector embedding generation is temporarily unavailable.
- The workshop owner can distinguish between high-confidence evidence and manual-review cases.

Risks:

- Embedding generation introduces API cost and latency.
- Poor chunking can reduce vector usefulness.
- Overconfident semantic matches can be dangerous if not labeled clearly.
- More moving parts means Phase 10 verification becomes even more important.

If verification fails:

- Keep text-mode RAG active as the fallback path.
- Disable vector-backed scoring in review output until retrieval quality is acceptable.
- Revisit chunking, normalization, and the chosen embedding model before enabling hybrid retrieval by default.

### Phase 10: End-To-End Verification And Hardening

Status: Pending.

#### Purpose

Prove the complete system is reliable after all changes. This phase repairs regressions and validates the runner, data path, UI actions, recovery, security, and real operator workflow. It also confirms that the console gives clear visual and audio feedback for real actions, uses Spanish labels, and renders clean UTF-8 text without stray mojibake.

#### Protected Final Test

A real new email is reserved for final acceptance. Do not process, alter, backfill, delete, or mark it during early diagnostics. Record its identifier only when the owner authorizes the final test.

#### Scope

Included:

- Gmail OAuth, query, cursor, startup backlog, and polling.
- Orbika extraction and retries.
- Matching, agentic review, preferences, optional RAG, DB, API, events, sound, and UI refresh.
- Every enabled UI action and failure state.
- Restart, duplicate prevention, recovery, retention, and secret checks.

Excluded:

- New matching capability.
- Corpus expansion beyond verification needs.
- Desktop packaging, which belongs to Phase 11.

#### Deliverables

- Versioned end-to-end matrix.
- Non-protected fixtures.
- Critical regression tests.
- Runner reliability report.
- UI action evidence.
- Defect register with retest results.
- Protected-email acceptance report.
- Updated runbook and recovery instructions.

#### Implementation Steps

1. Freeze features and record commit, migration, config, versions, counts, and backup.
2. Map every pipeline stage and every UI button to expected state and failure response.
3. Run unit, API, migration, and frontend checks in isolation.
4. Test runner startup and later polling with known fixtures, not the protected email.
5. Verify cursor advances at the correct boundary and retries do not duplicate data.
6. Compare a quote across DB, API list/detail, and UI.
7. Test start/stop runner, matching all/selected, agentic all/selected, refresh, pipeline, and activity.
8. Restart DB, API, frontend, and runner; reconcile stale states.
9. Verify cleanup dry-run, retention, Git exclusions, URL redaction, and secret handling.
10. Verify visual confirmations do not hide modal controls, modals close from the backdrop as well as the close button, and the top-left/toast layout stays readable on the main workflow.
11. Verify all visible UI text stays in Spanish and renders clean UTF-8 characters end to end.
12. After steps 1-11 pass, obtain approval and let the normal waiting runner discover the protected email naturally.
13. Confirm extraction, matching, review, persistence, notification, UI display, and no unwanted artifacts.
14. Ask the owner to review the result without terminal help and retest blocking issues.

#### Technical Verification

    cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline
    docker compose config
    docker compose up -d db
    docker compose ps
    docker compose exec db pg_isready -U orbika -d orbika_local
    python3 -m unittest
    cd apps/web
    npm run build

Also verify:

- Alembic is at expected head.
- API health reports PostgreSQL mode.
- Dashboard/list/detail agree with DB.
- Runner status reflects the real process.
- Duplicate checks return zero unexpected duplicates.
- No enabled UI action returns an unhandled 500.
- Sound fires once for a newly processed valid quote.
- Confirmation banners render away from the modal close control.
- Modal overlays dismiss from the backdrop and the `X` button.
- No visible text shows mojibake, stray `Ãƒâ€š`, or untranslated English labels in the operator flow.

#### Operational/Human Verification

- Owner recognizes ready, partial, failed, and waiting states.
- Owner understands provider links and warnings.
- Owner safely starts/stops waiting.
- Owner sees clear action feedback without UI elements covering controls.
- Owner can dismiss overlays by clicking outside them or with the close button.
- Owner reads the console entirely in Spanish.
- Recovery steps for Gmail, Orbika, DB, agentic review, and RAG are understandable.
- Protected email appears exactly once and is usable.

#### Acceptance Criteria

- Protected email reaches PostgreSQL and UI exactly once through normal flow.
- Startup backlog and waiting behavior pass repeated tests.
- All enabled UI buttons pass mapped scenarios.
- Restarts do not corrupt or duplicate data.
- Visual and audio confirmations are present, placed safely, and do not block controls.
- Console text is Spanish and UTF-8 clean in the verified operator surfaces.
- Critical/high defects are closed.
- Medium defects have accepted workaround and owner.
- CLI/JSON fallback remain as documented.
- Secrets are not committed or exposed.

#### Risks

- Tests can consume the protected email.
- Cursor changes can skip/duplicate messages.
- External services may be unavailable.
- UI may show stale runner state.
- Live tests modify real data.

#### If Verification Fails

- Stop at the failing boundary and preserve logs/state.
- Do not manually advance the cursor.
- Classify the failing layer.
- Add a regression test when feasible.
- Restore backup only when necessary and record it.
- Retest the failure and downstream checks.
- Do not start Phase 11 with a critical workflow failure.

### Phase 11: Simple Local Operation And Startup

Status: In progress.

Current progress: Blocks 1, 2, and 3 are implemented. The launcher now covers startup, shutdown, retention maintenance, provider refresh, supervision, and Windows task wrappers. Phase 11 stays in progress until the full Windows handoff, rehearsal, and packaging guidance are closed.

Operational supplier coverage note:

- Large autos catalog sources already added to the provider ecosystem:
  - `importadorasasociadas` - VTEX-based autos catalog with lazy-loaded category surfaces and captcha-aware crawling.
  - `imotriz` - large autos catalog recovered with manual captcha support; the latest usable snapshot contains `3788` records and should be treated as the current baseline.
  - Some providers, including `imotriz`, may require manual human validation during weekly extraction runs because the site can present captcha or human-verification prompts.
- Latest weekly refresh failure that still deserves visibility:
  - `partcar` - the weekly refresh failed with `IncompleteRead`, even though the latest saved snapshot remains large and usable (`9268` products).
- Large catalog providers that still remain worthwhile for future hardening or coverage closure:
  - `procar`
  - `propartes`
  - `corbeta`
  - `totus`
  - `autopartesercar`
  - `autopartesya`
  - `internacionaldepartes`
  - `universaldepartes`
  - `ppaautomotriz`
  - `redpuestos`
- Provider crawl lessons to keep for future integrations:
  - `redpuestos` confirmed that provider-specific live crawlers are safer than a shared generic browser flow.
  - Manual captcha handling must preserve the current scroll position and continue the same catalog surface after validation.
  - Do not auto-return to a home or product-detail page after captcha if the goal is a full catalog crawl; that can restart the traversal and lose progress.
  - Seed pages should stay on listing surfaces, and product-detail URLs should only be used as enrichment targets when needed.
  - Lazy-loading catalogs need a higher idle tolerance before the crawler assumes the surface is exhausted.


#### Purpose

Make the validated system feel like a normal local app for a non-technical Windows operator. WSL, Docker, PostgreSQL, FastAPI, Next.js, and the runner can remain internal.

#### Scope

Included:

- One manual startup entry point.
- Preflight for WSL, Docker, ports, credentials, DB, migrations, API, frontend, and runner.
- Controlled startup/shutdown and single-instance protection.
- Browser opening after health checks.
- Plain-language health and recovery.
- Backup/retention operations and reproducible corporate-PC setup.
- Periodic local maintenance designed for Windows operation.
- Safe scheduled cleanup for PostgreSQL and temporary local artifacts.
- Weekly provider refresh and runner health supervision.

Excluded:

- Automatic Windows boot startup.
- Cloud or multi-user deployment.
- Silent self-update.
- Native Windows rewrite without separate approval.

#### Execution Blocks

Phase 11 must be implemented in three controlled blocks, not as one large change. The document can define all three now, but execution should advance block by block with verification at the end of each block.

**Block 1: Simple Windows startup and shutdown**

Focus:

- single Windows launcher
- preflight and health gates
- controlled startup/shutdown
- browser opening after health checks
- plain-language recovery

Goal:
Make the system feel like one local app instead of a sequence of developer commands.

**Block 2: Periodic maintenance and retention**

Focus:

- PostgreSQL retention rules
- cleanup of expired local artifacts under `local/`
- safe maintenance command
- weekly Windows scheduled task
- visible maintenance status

Goal:
Prevent disk growth, stale artifacts, and long-term operational drift without requiring technical cleanup from the operator.

Status:
Complete for Block 2. The safe maintenance command, visible maintenance report, and weekly Windows scheduled-task installer are implemented. Windows verification completed: the scheduled task was registered successfully and an applied maintenance run removed expired local artifacts. The maintenance wrapper now forwards DATABASE_URL so PostgreSQL retention cleanup can run from the same scheduled Windows flow.


**Block 3: Supervision and weekly operational reliability**

Focus:

- runner health supervision
- stale-state detection
- weekly provider refresh
- visible success/failure status
- recovery guidance when routine tasks fail

Goal:
Ensure the system not only starts, but remains trustworthy week after week for a non-technical operator.

Status:
Implemented for Block 3. The launcher now exposes supervision and provider refresh reports, the API surfaces launcher status and a manual provider-refresh action, the UI shows the runner health and last weekly refresh result, and Windows wrappers exist for manual and scheduled provider refresh execution.

Execution rule:
Do not mark Phase 11 complete until all three blocks are implemented, verified, and rehearsed with the intended Windows workflow. Blocks 2 and 3 are already implemented; the remaining gate is a clean Windows operator rehearsal plus final packaging/handoff guidance.

#### Deliverables

- Windows-callable launcher and safe shutdown.
- Doctor/preflight command.
- Process/container reconciliation.
- Startup progress and actionable errors.
- First-run guide and one-page daily guide.
- Tested backup/restore.
- Redacted support bundle.
- Operator acceptance checklist.
- Windows scheduled-task plan for periodic maintenance.
- Retention policy applied to DB and `local/`.
- Weekly provider refresh routine with visible status.
- Runner health check with stale-state detection and recovery guidance.
- Windows wrappers and scheduled-task registration for weekly provider refresh.

#### Implementation Steps

1. Document supported Windows, WSL, Docker, Node, uv, browser, ports, and external credential paths.
2. Check Docker, ports 5433/8001/3000, credentials, DB health, migration, and duplicate instance.
3. Start DB and wait for health.
4. Apply only approved migrations or stop with clear guidance.
5. Start API on 8001 and frontend on 3000.
6. Keep waiting as a deliberate manual UI action, not Windows boot automation.
7. Open the browser only after API/UI health passes.
8. Stop runner first, then only Orbika processes, preserving DB data.
9. Add plain recovery and never show green status from stale state.
10. Define and implement retention rules for PostgreSQL data, generated JSON artifacts, traces, logs, and other temporary files under `local/`.
11. Add a safe maintenance command that can delete expired DB rows and removable local artifacts without touching active operational data.
12. Add a Windows-compatible scheduled-task strategy so the operator does not need to remember weekly cleanup manually.
13. Add a weekly provider-refresh task and make its latest success or failure visible in the UI or support diagnostics.
14. Add runner health supervision that can detect stale waiting state, repeated failures, or long periods without successful polling.
15. Add manual backup, disposable restore test, and redacted support bundle.
16. Create a Windows shortcut that calls the supported WSL launcher.
17. Rehearse full stop, first start, runner start, review, shutdown, second start, weekly maintenance, and provider refresh with the operator.

#### Technical Verification

- Preflight detects Docker stopped, occupied ports, missing credentials, wrong migration, and duplicate instance.
- Double start creates no duplicate runner/app process.
- Ports remain DB 5433:5432, API 8001, frontend 3000.
- Shutdown does not kill unrelated processes.
- Restart preserves data/state.
- Periodic maintenance does not delete current quotes needed for active work.
- DB retention removes only data older than the approved window.
- `local/` cleanup removes only temporary or expired artifacts.
- Weekly provider refresh leaves a timestamped success/failure record.
- Runner supervision detects stale health and failed polling without false green status.
- Backup and test restore succeed.
- Support bundle redacts secrets and signed URLs.
- Phase 10 suite passes from launcher path.

#### Operational/Human Verification

Without terminal help, the operator can:

1. Start the app.
2. Recognize healthy services.
3. Start waiting.
4. Review a quote.
5. Understand an error.
6. Retry a recoverable problem.
7. Stop safely.
8. Find the short help guide.
9. Understand whether weekly maintenance already ran or still needs attention.
10. Understand whether provider refresh succeeded this week.

#### Acceptance Criteria

- Daily workflow requires no terminal commands.
- One launcher starts the stack and opens UI.
- Waiting is deliberate and truthful.
- Duplicate instances are prevented.
- Common failures are actionable.
- Data survives restart.
- Expired DB and local artifacts can be cleaned safely on a schedule.
- Weekly maintenance can run without technical intervention.
- Provider refresh has a controlled weekly routine.
- Runner health is observable and stale state is not presented as healthy.
- Backup/restore are tested.
- Installation is reproducible on the corporate PC.

#### Risks

- Windows updates alter WSL/Docker integration.
- Browser/firewall blocks ports.
- Broad shutdown kills unrelated work.
- Unguarded automatic migration is risky.
- Shortcut hides diagnostics.
- Over-aggressive retention could delete useful audit or support data.
- Silent scheduled-task failure could create false trust in cleanup or provider refresh.
- Provider refresh may depend on external sites that change structure or availability.
- Weekly tasks can drift if Windows Task Scheduler or WSL permissions break.

#### If Verification Fails

- Keep documented manual commands as fallback.
- Stop at the failed health gate.
- Preserve redacted diagnostics and show recovery.
- Fix launcher/preflight without changing validated pipeline behavior.
- If cleanup fails, switch to dry-run mode and inspect affected targets before deleting anything.
- If provider refresh fails, preserve the last successful provider data and expose the failure clearly.
- Repeat complete operator rehearsal.

## Execution And Evidence Rules

Use one OpenClaw or Codex task per small implementation slice. Every task records:

- Phase and step.
- Objective and exclusions.
- Target repo and allowed paths.
- Files and migration revision.
- Commands and results.
- Human check required/completed.
- Limitations and fallback.
- Commit intentionally omitted or created.

Mark a phase done only when deliverables exist, technical gates pass, required human checks are recorded, critical defects are closed, migrations are verified, fallbacks remain available, and this document matches reality.

When a check fails:

1. Keep status Pending, In progress, or Blocked.
2. Record exact command, result, and boundary.
3. Fix the earliest faulty layer.
4. Add a regression case when feasible.
5. Rerun the failed and dependent checks.
6. Request human judgment only where needed.

## Recommended Execution Order

1. Phase 8.1 regression set and compatibility matrix.
2. Phase 8.1 implementation and owner review.
3. Decide whether Phase 8.2 is needed or keep it optional.
4. Start Phase 9 with corpus folder setup and approved-document pause.
5. Resume Phase 9 only after a small trusted corpus exists.
6. Freeze features and execute Phase 10.
7. Use the protected email only at the final Phase 10 gate.
8. Execute Phase 11.
9. Perform final operator rehearsal on the intended PC.

## Next Recommended Task

Complete the practical validation of Phase 9, then move toward Phase 10:

- Verify that `knowledge/rag_sources/` contains the curated technical PDFs.
- Run the RAG schema migration in PostgreSQL.
- Execute a dry-run ingestion first, then the real ingestion.
- Probe the indexed corpus with one or two real part-selection queries.
- Re-run agentic review on a controlled quote and confirm that compact technical evidence appears in the UI.
- Verification: ingestion succeeds without duplicates, retrieval returns useful citations, and the base pipeline still works if RAG is unavailable.

## Prompt Maestro Para OpenClaw

### Objetivo de esta seccion

Esta seccion deja un prompt maestro listo para usar con OpenClaw cuando se quiera avanzar en las fases finales sin gastar demasiados tokens en coordinacion manual. La idea no es pedirle a OpenClaw que cierre por si solo todos los detalles de integracion fina, sino que construya la base suficiente, haga la mayor parte del trabajo pesado, deje evidencia verificable y se detenga en puntos de control para que luego un modelo mas pequeno pueda revisar, ajustar y cerrar.

### Cuando usar este prompt maestro

Usar este prompt cuando ya exista una fase aprobada en este documento y se quiera delegar a OpenClaw la implementacion grande inicial. No usarlo para cambios pequenos o para dudas conversacionales. Si el cambio es chico, conviene crear una tarea puntual. Si el cambio afecta varias capas a la vez, conviene usar este prompt maestro y pedir una pausa obligatoria al terminar cada bloque importante.

### Regla operativa principal

OpenClaw debe priorizar:

- crear la base tecnica suficiente;
- dejar archivos, codigo, pruebas y documentacion inicial;
- registrar evidencia real;
- detenerse antes de cerrar detalles de integracion sensibles si no estan verificados extremo a extremo;
- no marcar una fase como completada sin evidencia real en Orbika.

La integracion fina, correcciones finales, ajustes menores de UI, depuracion puntual de runner o alineacion final entre funcionalidades puede completarse despues con una revision de menor costo.

### Tarea madre recomendada

La tarea madre recomendada para OpenClaw debe agrupar las fases finales como un programa de ejecucion por bloques, no como una sola implementacion ciega. Debe tomar este documento como contrato operativo y trabajar con pausas de control obligatorias.

Bloques sugeridos:

1. Fase 8 y 8.1: precision agentic y compatibilidad tecnica.
2. Fase 8.2 solo si la revision del dueno prueba que vale la pena.
3. Fase 9: base tecnica de RAG aplicada a seleccion de repuestos.
4. Fase 10: verificacion integral y hardening.
5. Fase 11: operacion simple para usuario no tecnico.

### Prompt maestro listo para OpenClaw

```text
Quiero crear y ejecutar una tarea madre de implementacion por bloques para las fases finales del proyecto Orbika-Quote-Intelligence-Pipeline.

Proyecto objetivo:
/home/julian95/projects/Orbika-Quote-Intelligence-Pipeline

Documento rector:
docs/architecture/orbika-implementation-phases.md

Objetivo general:
usar el plan detallado del documento para construir la base suficiente de las fases 8, 8.1, 8.2, 9, 10 y 11, sin intentar cerrar a ciegas todos los detalles finos de integracion. Quiero que OpenClaw haga la mayor parte del trabajo complejo, deje evidencia real y se detenga en puntos de control para revision posterior.

Reglas obligatorias:
- inspeccionar primero el repo real antes de editar;
- usar como contrato operativo las fases del documento;
- no crear funcionalidades fuera del alcance del plan;
- no hacer commit automatico;
- no marcar una fase como completada sin evidencia real;
- si una verificacion falla, dejar el bloqueo documentado y no simular exito;
- mantener compatibilidad con el flujo CLI existente;
- mantener compatibilidad con PostgreSQL, FastAPI y Next.js actuales;
- no romper el flujo de espera de nuevos correos;
- no tocar el correo real reservado para prueba final hasta llegar a la fase 10;
- si una tarea se vuelve demasiado grande, dividirla en subtareas ejecutables con evidencia.

Modo de trabajo requerido:
- crear o activar solo las tareas necesarias;
- ejecutar por bloques con pausa obligatoria al final de cada bloque;
- al terminar cada bloque, registrar:
  - archivos creados o modificados
  - verificaciones ejecutadas
  - resultado real
  - riesgos o puntos pendientes
  - recomendacion del siguiente paso

Bloque 1:
implementar lo necesario para Fase 8, 8.1 y 8.2 segun el documento:
- precision agentic mas util para el taller
- reglas de compatibilidad mas especificas
- preferencias controladas del taller o cliente
- comentarios breves, operativos y no decorativos
- base de datos, API y UI solo en el grado minimo necesario para soportar estas fases

Detenerse al finalizar Bloque 1 y no continuar automaticamente con Fase 9.

Bloque 2:
solo despues de aprobacion, implementar la base de Fase 9 segun el documento:
- RAG tecnico como complemento de seleccion de repuestos
- sin FAQ publica
- sin chatbot general
- enfocado en mejorar precision real de recomendacion
- con verificacion clara de que aporta a la decision y no solo agrega complejidad

Detenerse al finalizar Bloque 2 y no continuar automaticamente con Fase 10.

Bloque 3:
solo despues de aprobacion, ejecutar Fase 10 de verificacion integral y hardening:
- runner
- backend
- frontend
- botones de UI
- persistencia en DB
- reintentos y fallos esperables
- prueba protegida con el correo real reservado para validacion final

Detenerse al finalizar Bloque 3 y no continuar automaticamente con Fase 11.

Bloque 4:
solo despues de aprobacion, ejecutar Fase 11:
- arranque simple
- operacion local clara
- experiencia apta para usuario no tecnico

Criterio clave:
quiero que OpenClaw construya la base suficiente y documente bien cada bloque para que luego Codex en un modelo mas pequeno pueda revisar, corregir integraciones, ajustar archivos faltantes y cerrar el proyecto con menor costo.

No quiero una respuesta vaga. Quiero trabajo real por tareas, evidencia real y pausas de control.
```

### Como usarlo sin desperdiciar tokens

Secuencia recomendada:

1. Pedir a OpenClaw que cree la tarea madre a partir del prompt maestro.
2. Pedir a OpenClaw que ejecute solo el Bloque 1.
3. Esperar a que deje evidencia.
4. Volver a una revision mas barata para auditar lo que hizo.
5. Solo si el resultado es bueno, continuar con el siguiente bloque.

Esto reduce riesgo porque evita que OpenClaw avance demasiado sobre una base incorrecta y tambien reduce costo porque la revision fina se hace despues con un modelo mas economico.

### Que debe revisar Codex despues de cada bloque

Despues de cada bloque, la revision de cierre debe verificar como minimo:

- que OpenClaw si haya escrito en Orbika y no solo en openclaw-modern;
- que no haya dejado tareas marcadas como completadas sin evidencia real;
- que las verificaciones del bloque correspondan de verdad al alcance trabajado;
- que no haya roto el flujo de extraccion, matching, agentic review, API o UI existentes;
- que el documento de fases siga representando el estado real del proyecto;
- que los cambios pendientes para la siguiente fase esten claramente delimitados.

### Criterio de pausa obligatoria

Si OpenClaw reporta cualquiera de estos casos, no se debe continuar automaticamente con el siguiente bloque:

- verificacion clave fallida;
- evidencia incompleta;
- cambios grandes sin pruebas;
- bloqueo por permisos o rutas;
- cambios en una capa que no se reflejan todavia en API, DB o UI;
- regresion en el runner de correos o en la visualizacion de cotizaciones.

En esos casos, primero se revisa, corrige y estabiliza el bloque actual.

### Resultado esperado de esta seccion

El proyecto queda con una forma clara de delegar trabajo pesado a OpenClaw sin perder control. OpenClaw construye la base grande por bloques y Codex remata integracion, correcciones y coherencia final. Ese es el esquema recomendado para ahorrar tokens y mantener calidad.
















## Reminder Notes Added After Current Phase Review

- Add the city for every provider and expose it in the page/UI so the operator can identify supplier location during review.
- Generate an incremental Excel file for client delivery with the correct quotes that have at least one matched supplier part, even if it is only one part.
- This Excel file must keep accumulating rows with each new quote instead of following the DB/local-artifact maintenance policy.
- Do not auto-delete rows from this Excel file; the client decides whether old delivered rows remain or are removed.
- The Excel file should include the full quote information required for delivery, not only the matched part fragment.

