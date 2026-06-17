# Visual Console

## Overview

This repository now includes a local visual operations console built on top of the existing Python pipeline.

Components:

- `apps/api`: FastAPI API layer
- `apps/web`: Next.js frontend
- `docker-compose.yml`: local stack for WSL/Docker Desktop

The API does not replace the current CLI scripts. It shells out to the existing tools under `tools/`.

## Local API Run

From the repo root:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline

uv run uvicorn --app-dir apps/api orbika_console_api.main:app --reload --host 0.0.0.0 --port 8000
```

## Local Frontend Run

From the repo root:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline/apps/web
npm install
npm run dev
```

The frontend expects the API at:

```text
http://localhost:8000
```

## Docker Compose

From the repo root:

```bash
docker compose up --build
```

Frontend:

```text
http://localhost:3000
```

API:

```text
http://localhost:8000
```

## Current API Capabilities

- `GET /api/dashboard`
- `GET /api/quotes`
- `GET /api/quotes/{quote_key}`
- `GET /api/tasks`
- `POST /api/tasks/incremental-runner/start`
- `POST /api/tasks/{task_id}/stop`
- `POST /api/tasks/supplier-matching/run`
- `POST /api/tasks/agentic-review/run`
- `GET /api/events` for SSE

Both matching endpoints accept an optional `quote_keys` array to process only a selected subset from the UI.

## Notes

- The runner still uses the existing Gmail and Orbika scripts.
- Orbika login remains disabled by default unless `allow_login_fallback` is explicitly requested.
- Sound notifications are emitted in the browser when a new quote is detected by the SSE stream.
- The UI focuses on structured viewing of quote files, not raw JSON dumping.

## Environment Caveats Seen In This WSL

- `docker compose` will only work if Docker Desktop WSL integration is enabled for this distro. In the current environment, `docker` was not available inside WSL.
- `npm install` will only work if `node` is installed inside WSL or correctly bridged into WSL. In the current environment, `npm` resolved to `/mnt/c/nvm4w/nodejs/npm` but failed because `node` was not available in the WSL `PATH`.
- The backend Python modules passed syntax validation with `python3 -m py_compile`, but a full frontend build could not be executed until the Node issue above is fixed.
