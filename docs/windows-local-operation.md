# Windows Local Operation

This guide covers the Windows launcher introduced through Phase 11 Blocks 1, 2, and 3.

## What It Does

The launcher keeps WSL, Docker, PostgreSQL, FastAPI, Next.js, and the runner internal. The Windows operator only needs four actions:

- Diagnose
- Start
- Stop
- Maintenance
- Weekly provider refresh
- Optional Windows scheduled tasks for maintenance and provider refresh

## Windows Entry Points

Use the files under `scripts/windows/`:

- `Diagnosticar-OrbikaConsole.cmd`
- `Start-OrbikaConsole.cmd`
- `Stop-OrbikaConsole.cmd`
- `Maintenance-OrbikaConsole.cmd`
- `ProviderRefresh-OrbikaConsole.cmd`
- `Register-OrbikaMaintenanceTask.cmd`
- `Register-OrbikaProviderRefreshTask.cmd`

The `.cmd` files call the `.ps1` wrappers, which then execute the launcher flow.

The maintenance installer registers a weekly Windows Task Scheduler entry that calls the shipped maintenance wrapper automatically. The operator only needs to run it once from Windows. The maintenance wrapper now passes `DATABASE_URL` into WSL as well, so the scheduled task can clean PostgreSQL retention data and local artifacts in the same run.

Default schedule:

- Sunday at 08:00 local time for maintenance
- Sunday at 09:00 local time for provider refresh
- weekly maintenance uses the safe cleanup command with `--apply`
- weekly provider refresh reruns supplier matching, IA review, and PostgreSQL sync
- the tasks can be re-registered with `-Force` if the schedule changes

## WSL Launcher

The real launcher lives in:

- `tools/local_console_launcher.py`

Available commands:

- `preflight`
- `status`
- `start`
- `stop`
- `maintenance`
- `provider-refresh`

## What `start` Does

1. Runs preflight checks.
2. Starts PostgreSQL with `docker compose up -d db`.
3. Applies approved Alembic migrations.
4. Starts the API on port `8001` if it is not already healthy.
5. Starts the frontend on port `3000` if it is not already healthy.
6. Writes runtime state to `local/launcher/state.json`.
7. Exposes supervision status and stale-runner hints through the API.
8. Opens the browser to `http://localhost:3000`.

## What `stop` Does

1. Tries to stop the incremental runner through the API first.
2. Stops only the API and frontend PIDs tracked by the launcher.
3. Stops the PostgreSQL container by default.
4. Removes the launcher state file.

## Logs And Runtime State

The launcher writes runtime files here:

- `local/launcher/state.json`
- `local/launcher/api.log`
- `local/launcher/web.log`
- `local/launcher/maintenance.json`
- `local/launcher/provider_refresh.json`

## Manual WSL Commands

If needed, the same launcher can be called directly from WSL:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline
PYTHONPATH=. python3 tools/local_console_launcher.py preflight
PYTHONPATH=. python3 tools/local_console_launcher.py status
PYTHONPATH=. python3 tools/local_console_launcher.py start
PYTHONPATH=. python3 tools/local_console_launcher.py stop
PYTHONPATH=. python3 tools/local_console_launcher.py maintenance --apply
PYTHONPATH=. python3 tools/local_console_launcher.py provider-refresh --limit-per-part 5
```

## Supervision And Weekly Refresh

The launcher status endpoint now exposes three operational sections:

- `maintenance`: last retention run and cleanup summary
- `provider_refresh`: last weekly provider refresh result
- `supervision`: runner health, stale-state detection, and recovery guidance

The frontend uses these fields to show:

- whether the runner is healthy, paused, stale, or failing
- the last weekly provider refresh result
- a one-click action to rerun the provider refresh manually

## Current Limits

- It assumes the WSL distro is `Ubuntu-26.04`.
- It assumes Node is available through `nvm use 22`.
- It assumes PostgreSQL should run on host port `5433`, API on `8001`, and frontend on `3000`.
- The launcher now exposes the periodic maintenance command and visible maintenance status, while supervision remains part of the remaining Phase 11 hardening work.