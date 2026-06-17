# Orbika PostgreSQL Migrations

Migration tool: Alembic.

Reason: Orbika is a Python project, Alembic is the standard migration runner for
PostgreSQL-backed Python services, and this phase can keep the schema as
explicit SQL without coupling runtime code to ORM models.

Current scope:

- Prepare local PostgreSQL schema only.
- Do not import JSON data.
- Do not change runner, API, frontend, supplier matching or agentic review
  behavior.

Run from WSL:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline
docker compose up -d db
docker compose exec db pg_isready -U orbika -d orbika_local
DATABASE_URL=postgresql+psycopg://orbika:orbika_local_dev_password@localhost:5432/orbika_local uv run --with alembic --with "psycopg[binary]" alembic upgrade head
DATABASE_URL=postgresql+psycopg://orbika:orbika_local_dev_password@localhost:5432/orbika_local uv run --with alembic --with "psycopg[binary]" alembic current
```
