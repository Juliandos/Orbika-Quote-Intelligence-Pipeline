# Phase 6 Output Policy

Phase 6 reduces local Orbika pipeline artifacts now that PostgreSQL is the
operational source of truth for the app.

## Goals

- Keep resume and compatibility behavior intact.
- Reduce dependency on local folders for daily operation.
- Make expensive debug artifacts opt-in.
- Provide a safe cleanup path instead of manual folder deletion.

## Output Roles

### Keep by default

- `local/orbika_incremental/state.json`
  - Required for resume and polling continuity.
- `local/orbika_incremental/quotes/`
  - Compatibility/debug minimum.
- `local/orbika_incremental/daily/`
  - Regenerable summaries, still useful for quick audits.

### Debug-only or short retention

- `local/orbika_incremental/agentic_traces/`
- `local/orbika_incremental/snapshots/`
- `local/orbika_incremental/debug/`

These should not be required for ordinary operation and should be kept only when
actively debugging extraction or review quality.

### Experimental artifacts

Examples:

- `check-*`
- `backfill-*`
- `phase*`
- `retest-*`

These are valid during verification work, but should be treated as temporary.

## Runner Modes

The incremental runner now supports:

- `minimal`
  - `state.json`, `quotes/`, `daily/`
- `standard`
  - `minimal` + `agentic_traces/`
- `debug`
  - `standard` + `snapshots/`

Default mode is `minimal`.

Explicit `--snapshot-dir` or `--agentic-trace-dir` arguments override the mode
when a specific run needs more artifacts.

## Cleanup

Use the cleanup helper in dry-run mode first:

```bash
PYTHONPATH=. uv run python tools/cleanup_incremental_outputs.py
```

Apply after reviewing candidates:

```bash
PYTHONPATH=. uv run python tools/cleanup_incremental_outputs.py --apply
```

Default cleanup targets:

- debug artifacts older than 7 days
- experimental artifacts older than 7 days
