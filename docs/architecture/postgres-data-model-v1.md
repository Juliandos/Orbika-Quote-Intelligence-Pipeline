# PostgreSQL Data Model V1

Date: 2026-06-17

Scope: Phase 2 design document for the future PostgreSQL persistence layer of
`Orbika-Quote-Intelligence-Pipeline`.

This document is design only. It does not implement PostgreSQL, create
migrations, modify the runner, change FastAPI endpoints, change Next.js, or
alter productive code.

## Goals

- Move the operational source of truth from scattered JSON files toward
  PostgreSQL in a controlled future phase.
- Keep the current CLI and JSON outputs working during migration.
- Support a local manual app for a workshop operator who should not interact
  with folders, JSON files or terminals.
- Prepare the data model for supplier matching, agentic review, customer
  preferences, RAG and future assistants.
- Keep generated files minimal and treat snapshots/traces as hidden technical
  artifacts, not product data.

## Principles

- PostgreSQL stores data that is queried, filtered, related, audited or used for
  a user decision.
- Files remain only for examples, temporary debug evidence, large traces or
  external artifacts that should not be displayed to the operator.
- Every external item must have a stable natural key when possible, so imports
  are idempotent.
- The migration should support read-through/write-through while the CLI remains
  compatible.
- Human operational states must be explicit. A quote can be technically
  processed but still require human review.

## Core Entity Model

```text
emails
  -> quotes
      -> vehicles
      -> workshops
      -> parts
          -> supplier_matches
          -> agentic_reviews
  -> tasks
  -> events

customer_preferences
  -> agentic_reviews

daily_summaries
  -> compact aggregate view by date
```

Future agent/RAG layer:

```text
rag_documents
  -> rag_chunks

agent_sessions
  -> agent_messages
  -> business_memory
  -> human_handoffs
```

## Enum-Like States

Use PostgreSQL enums only if the team is comfortable maintaining enum
migrations. Otherwise use constrained text values first.

### Quote Status

- `new`: quote link or email detected but not processed.
- `pending_extraction`: queued for Orbika extraction.
- `extracting`: extraction is in progress.
- `extracted`: Orbika data was extracted successfully.
- `pending_matching`: waiting for supplier matching.
- `matching`: supplier matching is in progress.
- `pending_agentic_review`: waiting for agentic review.
- `agentic_reviewing`: agentic review is in progress.
- `ready_for_review`: ready for workshop operator decision.
- `needs_manual_review`: data exists but requires human attention.
- `quoted`: operator prepared or accepted quote response.
- `sent`: quote response was sent or marked as sent.
- `failed`: unrecoverable failure for the current attempt.
- `needs_retry`: recoverable failure; user or system may retry.
- `archived`: outside active operating window or intentionally hidden.

### Part Status

- `requested`
- `matched`
- `no_match`
- `needs_review`
- `accepted`
- `discarded`

### Task Status

- `queued`
- `running`
- `completed`
- `failed`
- `cancelled`
- `blocked`

### Match Review Decision

- `recommended`
- `possible`
- `risky`
- `rejected`
- `manual_confirmation_required`

## Tables

### `emails`

Purpose: track Gmail inputs and avoid reprocessing the same message.

Key fields:

- `id uuid primary key`
- `gmail_id text unique not null`
- `message_id text`
- `thread_id text`
- `sender text not null`
- `subject text`
- `received_at timestamptz`
- `internal_date_ms bigint`
- `extraction_status text not null`
- `quote_url_count integer not null default 0`
- `warnings jsonb not null default '[]'`
- `raw_excerpt text`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

Recommended indexes:

- unique index on `gmail_id`
- index on `received_at desc`
- index on `extraction_status`
- trigram or full-text index on `subject` later if search needs it

### `quotes`

Purpose: main operational record shown in the quote inbox.

Key fields:

- `id uuid primary key`
- `quote_key text unique not null`
- `email_id uuid references emails(id)`
- `aviso_id text`
- `insurer text`
- `source_subject text`
- `quote_url_masked text`
- `quote_url_hash text`
- `load_status text`
- `status text not null`
- `priority text default 'normal'`
- `received_at timestamptz`
- `processed_at timestamptz`
- `ready_for_review_at timestamptz`
- `sent_at timestamptz`
- `last_error text`
- `warnings jsonb not null default '[]'`
- `source_file_path text`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

Recommended indexes:

- unique index on `quote_key`
- index on `status`
- index on `received_at desc`
- index on `aviso_id`
- index on `source_subject`
- composite index on `(status, received_at desc)`

Notes:

- Store masked URL and optionally a hash of the full URL, not the full URL by
  default.
- `source_file_path` is temporary migration metadata, not a product dependency.

### `vehicles`

Purpose: structured vehicle context for compatibility checks.

Key fields:

- `id uuid primary key`
- `quote_id uuid unique references quotes(id) on delete cascade`
- `plate text`
- `brand text`
- `line text`
- `version text`
- `model_year integer`
- `vin text`
- `color text`
- `raw_payload jsonb not null default '{}'`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

Recommended indexes:

- index on `plate`
- index on `(brand, line, model_year)`
- index on `vin` when present

### `workshops`

Purpose: workshop and delivery context extracted from Orbika.

Key fields:

- `id uuid primary key`
- `quote_id uuid unique references quotes(id) on delete cascade`
- `commercial_name text`
- `delivery_workshop text`
- `city text`
- `address text`
- `phone text`
- `raw_payload jsonb not null default '{}'`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

Recommended indexes:

- index on `commercial_name`
- index on `city`

### `parts`

Purpose: requested parts from a quote.

Key fields:

- `id uuid primary key`
- `quote_id uuid references quotes(id) on delete cascade`
- `position integer not null`
- `name text not null`
- `normalized_name text`
- `requested_reference text`
- `quantity numeric`
- `raw_status text`
- `status text not null default 'requested'`
- `observations text`
- `raw_payload jsonb not null default '{}'`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

Recommended indexes:

- unique index on `(quote_id, position)`
- index on `status`
- index on `normalized_name`
- GIN full-text index on `name` later if needed

### `supplier_matches`

Purpose: supplier candidate options for each requested part.

Key fields:

- `id uuid primary key`
- `part_id uuid references parts(id) on delete cascade`
- `provider_id text not null`
- `provider_name text`
- `product_name text not null`
- `reference text`
- `sku text`
- `brand text`
- `category_name text`
- `subcategory_name text`
- `detail_url text`
- `detail_url_hash text`
- `price numeric`
- `currency text default 'COP'`
- `availability text`
- `match_type text`
- `score_percent integer not null`
- `rank integer`
- `reasons jsonb not null default '[]'`
- `risk_flags jsonb not null default '[]'`
- `snapshot_ref text`
- `raw_payload jsonb not null default '{}'`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

Recommended indexes:

- index on `part_id`
- index on `provider_id`
- index on `(part_id, rank)`
- index on `(part_id, score_percent desc)`
- index on `match_type`

Notes:

- `risk_flags` should eventually capture issues such as incompatible year,
  wrong side, wrong trim, model mismatch or low lexical overlap.
- `detail_url` can be stored if needed for operation, but sensitive URLs should
  be masked or hashed when appropriate.

### `agentic_reviews`

Purpose: concise assisted ranking and decision support for a part.

Key fields:

- `id uuid primary key`
- `part_id uuid references parts(id) on delete cascade`
- `reviewer_mode text not null`
- `model text`
- `status text not null`
- `top_match_id uuid references supplier_matches(id)`
- `confidence_percent integer`
- `summary_comment text`
- `selected_options jsonb not null default '[]'`
- `risk_notes jsonb not null default '[]'`
- `preference_notes jsonb not null default '[]'`
- `trace_file_path text`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

Recommended indexes:

- index on `part_id`
- index on `status`
- index on `created_at desc`

Notes:

- Keep at most the top three options in UI-facing review summaries.
- Full traces remain files during early phases; DB stores summary and pointer.

### `customer_preferences`

Purpose: business preferences that influence recommendations.

Key fields:

- `id uuid primary key`
- `scope text not null`
- `scope_key text`
- `preference_type text not null`
- `value jsonb not null`
- `notes text`
- `active boolean not null default true`
- `created_by text`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

Recommended indexes:

- index on `(scope, scope_key)`
- index on `preference_type`
- partial index on `active where active = true`

Examples:

- preferred supplier by category
- supplier to avoid
- acceptable risk level for year compatibility
- preferred brands
- delivery time preference

### `tasks`

Purpose: operational task/run history for the local app.

Key fields:

- `id uuid primary key`
- `task_key text unique`
- `kind text not null`
- `status text not null`
- `triggered_by text`
- `started_at timestamptz`
- `finished_at timestamptz`
- `exit_code integer`
- `input_payload jsonb not null default '{}'`
- `result_payload jsonb not null default '{}'`
- `counters jsonb not null default '{}'`
- `log_file_path text`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

Recommended indexes:

- index on `kind`
- index on `status`
- index on `started_at desc`

### `events`

Purpose: live and historical operational event stream.

Key fields:

- `id uuid primary key`
- `event_type text not null`
- `quote_id uuid references quotes(id)`
- `task_id uuid references tasks(id)`
- `severity text not null default 'info'`
- `message text`
- `payload jsonb not null default '{}'`
- `created_at timestamptz not null default now()`

Recommended indexes:

- index on `created_at desc`
- index on `event_type`
- index on `quote_id`
- index on `task_id`

### `daily_summaries`

Purpose: compact daily reporting without relying on regenerated daily files.

Key fields:

- `id uuid primary key`
- `summary_date date unique not null`
- `quotes_total integer not null default 0`
- `quotes_ready integer not null default 0`
- `quotes_failed integer not null default 0`
- `parts_total integer not null default 0`
- `parts_with_matches integer not null default 0`
- `provider_hits jsonb not null default '{}'`
- `payload jsonb not null default '{}'`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

Recommended indexes:

- unique index on `summary_date`
- index on `summary_date desc`

## Future Tables

### `rag_documents`

Stores metadata for PDFs, manuals, catalogs and technical documents used by
future RAG.

Key fields:

- `id uuid primary key`
- `title text not null`
- `source_type text`
- `source_uri text`
- `file_path text`
- `sha256 text unique`
- `language text`
- `status text not null`
- `metadata jsonb not null default '{}'`
- `created_at timestamptz not null default now()`

### `rag_chunks`

Stores searchable chunks and embeddings in a later phase.

Key fields:

- `id uuid primary key`
- `document_id uuid references rag_documents(id) on delete cascade`
- `chunk_index integer not null`
- `content text not null`
- `metadata jsonb not null default '{}'`
- `embedding vector`
- `created_at timestamptz not null default now()`

Note: the `vector` type assumes a future `pgvector` decision. Do not add it
until the RAG implementation phase confirms the embedding provider and
deployment approach.

### `agent_sessions`

Stores future assistant conversations.

Key fields:

- `id uuid primary key`
- `session_type text not null`
- `status text not null`
- `started_at timestamptz not null default now()`
- `ended_at timestamptz`
- `metadata jsonb not null default '{}'`

### `agent_messages`

Stores messages for future customer-service and owner-assistant chats.

Key fields:

- `id uuid primary key`
- `session_id uuid references agent_sessions(id) on delete cascade`
- `role text not null`
- `content text not null`
- `tool_calls jsonb not null default '[]'`
- `created_at timestamptz not null default now()`

### `business_memory`

Stores durable business knowledge approved by the owner.

Key fields:

- `id uuid primary key`
- `memory_type text not null`
- `content text not null`
- `source text`
- `active boolean not null default true`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

### `human_handoffs`

Stores future transfers from automation to a human operator.

Key fields:

- `id uuid primary key`
- `session_id uuid references agent_sessions(id)`
- `quote_id uuid references quotes(id)`
- `reason text not null`
- `status text not null`
- `assigned_to text`
- `created_at timestamptz not null default now()`
- `resolved_at timestamptz`

## Migration Strategy From JSON

### Phase 3: Import-Only

- Create an importer that reads `local/orbika_incremental/quotes/*.json`.
- Upsert `emails`, `quotes`, `vehicles`, `workshops`, `parts`,
  `supplier_matches` and `agentic_reviews`.
- Use `quote_key` as the stable quote identity.
- Use Gmail `gmail_id` as the stable email identity when present.
- Use `(quote_id, position)` as the initial stable part identity.
- Record `source_file_path` during migration for traceability.
- Do not delete or rewrite JSON files.

### Phase 4: API Reads From DB

- FastAPI reads quote lists and details from PostgreSQL.
- Keep a temporary fallback to JSON if the database is empty or if a quote has
  not been imported.
- UI should not need to know which backend source was used.

### Phase 5: Write-Through

- Existing runner continues producing JSON while also persisting to
  PostgreSQL.
- Supplier matching writes both compact JSON and DB records.
- Agentic review writes concise DB summaries and optional trace file pointers.
- Once stable, JSON generation can be reduced to support/debug mode.

## Retention Rules

Initial policy:

- Quotes and related operational rows: keep active 90 days.
- Logs/tasks/events: keep detailed rows 30 days; compact summaries can remain.
- Debug snapshots: disabled by default; if enabled, purge after 7 days.
- Full agentic traces: keep 30 to 90 days depending on debugging value.
- Daily summaries: keep compact summaries long-term.
- Golden examples: keep one curated example under `docs/examples/golden-quote/`.

Implementation note for later:

- Add a scheduled/manual maintenance command in a future phase.
- Archive before delete if the owner wants historical business analytics.
- Never purge active, failed, disputed or manually pinned quotes without a clear
  operator decision.

## Recommended Indexes Summary

- `emails(gmail_id)` unique
- `emails(received_at desc)`
- `quotes(quote_key)` unique
- `quotes(status, received_at desc)`
- `quotes(aviso_id)`
- `vehicles(plate)`
- `vehicles(brand, line, model_year)`
- `parts(quote_id, position)` unique
- `parts(status)`
- `supplier_matches(part_id, rank)`
- `supplier_matches(part_id, score_percent desc)`
- `supplier_matches(provider_id)`
- `agentic_reviews(part_id)`
- `tasks(kind, status)`
- `tasks(started_at desc)`
- `events(created_at desc)`
- `daily_summaries(summary_date)` unique

## Risks

- Migrating too early could break the working CLI. Keep JSON compatibility until
  DB-backed behavior is verified.
- Full traces and snapshots can become large. Store summaries in DB and keep
  bulky files hidden and temporary.
- Supplier data may not have stable IDs. Use provider, URL hash, SKU/reference
  and product name together where necessary.
- Quote status and human review status can diverge. Keep technical status and
  operator decision fields explicit.
- Full URLs and tokens may be sensitive. Prefer masked URLs, hashes and files
  outside the repo for secrets.
- RAG and agents should not be mixed into the first PostgreSQL implementation.
  Prepare tables conceptually, but implement later.

## Acceptance Criteria For Moving To Implementation

Before implementing migrations:

- This document is reviewed and accepted.
- The team confirms table names and quote statuses.
- Retention rules are accepted by the business owner.
- The import identity strategy is accepted: `quote_key`, `gmail_id`,
  `(quote_id, position)`.
- A decision is made about migration tooling: Alembic, SQLModel metadata,
  raw SQL files or another project-standard approach.
- Docker/PostgreSQL startup strategy is confirmed for WSL and future Windows
  packaging.
- A rollback plan exists for the first import.

## Next Phase

Recommended next phase:

```text
Phase 2.1: PostgreSQL infrastructure and migrations
```

Scope for that future phase:

- Add PostgreSQL service configuration.
- Add migration tooling.
- Create the initial schema from this design.
- Add a minimal database health check.
- Do not yet switch the API or runner until migrations are verified.
