# Phase 6 Reminders

This note records follow-up ideas for the Phase 6 output reduction work.

## Current State

- `state.json` stays as the local resume anchor.
- `quotes/` remains as a minimal compatibility/debug artifact.
- `daily/` remains regenerable.
- `agentic_traces/`, `snapshots/` and `debug/` are now treated as short-retention or opt-in debug artifacts.

## Next Reduction Step

Phase 6 should be reduced even further in a later iteration.

Desired follow-up direction:

- make PostgreSQL the only operational source of truth for normal use
- reduce or eliminate per-quote JSON generation by default if the UI/API can read from DB directly
- consider moving daily summaries to DB-backed or on-demand generation
- keep only the smallest possible local state needed for resume and debugging

## Reminder

Do not remove these compatibility files yet unless the next iteration is explicitly validated:

- `local/orbika_incremental/state.json`
- `local/orbika_incremental/quotes/`

The next step should be planned as a separate tightening pass, not as an automatic cleanup.


Agregar recordatorio de que la última fase es verificar que todo funcione bien porque por ahora no espra correos, quiero ver bien lo de la retoma de correos, funcionamiento autónomo, que todos los botones de la ui funcionen correctamente, poder recibir mas proveedores, db actualizada.