# PostgreSQL Local Setup

Date: 2026-06-17

Scope: Phase 2.1 local PostgreSQL infrastructure for Orbika. This setup does
not change the productive runner, FastAPI reads, Next.js, supplier matching,
agentic review or JSON import behavior.

## Migration Tool

Recommended tool: Alembic.

Alembic fits this repository because Orbika is already a Python project and the
first schema can be managed as explicit PostgreSQL SQL without introducing ORM
models into runtime code. The initial migration implements the core tables from
`docs/architecture/postgres-data-model-v1.md` and intentionally leaves future
RAG and assistant tables for a later phase.

## Environment

Use `.env.example` as the non-secret template for local variables:

```bash
cp .env.example .env
```

The default password is only a local development placeholder. Replace it in
your private `.env` if needed, and do not commit real credentials.

## Start PostgreSQL In WSL

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline
docker compose up -d db
```

Check container health:

```bash
docker compose ps db
docker compose exec db pg_isready -U orbika -d orbika_local
```

Validate a SQL connection:

```bash
docker compose exec db psql -U orbika -d orbika_local -c "select current_database(), current_user;"
```

## Run Migrations

From WSL host:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline
export DATABASE_URL="postgresql+psycopg://orbika:orbika_local_dev_password@localhost:5432/orbika_local"
uv run --with alembic --with "psycopg[binary]" alembic upgrade head
uv run --with alembic --with "psycopg[binary]" alembic current
```

Expected current revision:

```text
20260617_0001
```

## Basic Schema Check

```bash
docker compose exec db psql -U orbika -d orbika_local -c "\dt"
docker compose exec db psql -U orbika -d orbika_local -c "select version_num from alembic_version;"
```

Expected core tables include:

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

## Import Existing JSON Quotes

Phase 3 adds a manual importer from the current local JSON files into
PostgreSQL. It reads `DATABASE_URL`, leaves the JSON files unchanged, and is
idempotent by `quotes.quote_key`.

Use the local host port from `docker-compose.yml`:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline
export DATABASE_URL="postgresql+psycopg://orbika:orbika_local_dev_password@localhost:5433/orbika_local"
```

Validate a small sample without committing database changes:

```bash
uv run python tools/import_quotes_to_postgres.py --limit 1 --dry-run
```

Import a small sample:

```bash
uv run python tools/import_quotes_to_postgres.py --limit 1
```

Confirm row counts in PostgreSQL:

```bash
docker compose exec db psql -U orbika -d orbika_local -c "select 'emails' as table_name, count(*) from emails union all select 'quotes', count(*) from quotes union all select 'vehicles', count(*) from vehicles union all select 'workshops', count(*) from workshops union all select 'parts', count(*) from parts union all select 'supplier_matches', count(*) from supplier_matches union all select 'agentic_reviews', count(*) from agentic_reviews order by table_name;"
```

## Stop Local Database

```bash
docker compose stop db
```

Do not run destructive volume cleanup unless explicitly intended:

```bash
docker compose down -v
```
