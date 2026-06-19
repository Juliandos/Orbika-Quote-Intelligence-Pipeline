# Incremental Orbika Quote Runner

Local read-only runner that connects the Gmail quote-link extractor with the
Orbika quote-page extractor.

It processes new messages from `cotizacionesorbika@subocol.com`, extracts every
`quote_url`, opens each Orbika quote in a browser session, captures rendered
replacement-part data, matches each extracted part against the local supplier
catalog snapshots, runs the local agentic supplier review, persists the enriched
quote to PostgreSQL when `DATABASE_URL` is configured, and writes one independent
JSON file per quote.

As of Phase 6, PostgreSQL is the operational source of truth and local files are
kept mainly for compatibility, resume state and targeted debugging.

## Safety

- Gmail uses only `https://www.googleapis.com/auth/gmail.readonly`.
- Orbika is opened only to read the rendered quote page.
- The runner does not reply, label, archive or delete Gmail messages.
- The runner does not submit, approve, reject or mutate Orbika quotes.
- Gmail OAuth files, Orbika credentials and Playwright storage state must stay
  outside this repository.
- Full quote URLs are stored only in local output files under ignored `local/`
  paths; logs use masked URLs where applicable.

## State And Resume

Default state path:

```text
local/orbika_incremental/state.json
```

The state file contains:

- `cursor`: highest completed Gmail message marker.
- `current`: current Gmail message, quote key and processing stage.
- `messages`: per-message status, extracted quote keys and warnings.
- `quotes`: per-quote status, masked URL, output path, load status and notice ID.
- `last_run`: counters from the latest run.

Each quote JSON now also includes:

- `supplier_matching.summary`: coverage and exact-match totals.
- `supplier_matching.parts`: top supplier candidates per extracted Orbika part.
- `supplier_matching.provider_specs`: provider capabilities and limitations.
- `agentic_supplier_matching.summary`: reviewed parts and selected provider hits.
- `agentic_supplier_matching.parts`: final agentic selections per part.

The runner executes agentic review in the same quote processing pass by default.
Use `--skip-agentic-review` only for diagnostics or compatibility runs where the
expected output is quote extraction plus supplier matching without final review.
When agentic review runs, PostgreSQL persistence receives the enriched JSON and
can insert `agentic_reviews` rows in the same transaction used for quote, parts
and supplier matches.

If the process stops, rerun the same command. The runner first reloads any
message that is not marked `completed`, then polls the latest Gmail messages.
Already processed quote keys are skipped unless `--reprocess` is used.

Each quote key is stable for:

```text
message_id + quote_url
```

That lets one email contain multiple quote URLs without duplicating work.

## Setup

Keep Gmail OAuth client secrets outside the repo:

```bash
mkdir -p ~/.config/openclaw/gmail
chmod 700 ~/.config/openclaw/gmail
```

Use a shell-only environment for Orbika credentials:

```bash
export ORBIKA_USERNAME="your-user"
read -s ORBIKA_PASSWORD
export ORBIKA_PASSWORD
```

Install the Playwright browser locally if needed:

```bash
uv run --with playwright python -m playwright install chromium
```

## Run Once

From the repo root:

```bash
uv run \
  --with google-api-python-client \
  --with google-auth-oauthlib \
  --with playwright \
  python tools/incremental_orbika_quote_runner.py \
  --credentials ~/.config/openclaw/gmail/autolujoslaser1-client-secret.json \
  --max-results 50
```

Default local outputs in the default `minimal` mode:

```text
local/orbika_incremental/state.json
local/orbika_incremental/quotes/<quote_key>.json
local/orbika_incremental/daily/YYYY-MM-DD.json
local/orbika_incremental/daily/YYYY-MM-DD.md
```

Additional outputs are available when needed:

```text
standard mode:
  local/orbika_incremental/agentic_traces/<quote_key>.agentic_trace.json

debug mode:
  local/orbika_incremental/snapshots/<quote_key>/quote-<retry>.html
```

## Poll For New Mail

Run continuously with a polling interval:

```bash
uv run \
  --with google-api-python-client \
  --with google-auth-oauthlib \
  --with playwright \
  python tools/incremental_orbika_quote_runner.py \
  --credentials ~/.config/openclaw/gmail/autolujoslaser1-client-secret.json \
  --max-results 50 \
  --poll-seconds 300
```

Stop with `Ctrl+C`. Start the same command later to resume from the state file.

## Useful Options

- `--state-path`: custom local state file path.
- `--file-output-mode`: `minimal`, `standard`, or `debug`.
- `--quotes-dir`: custom per-quote JSON output directory.
- `--snapshot-dir`: custom rendered HTML snapshot directory.
- `--providers-root`: local supplier snapshot root, default `supplier_catalog/providers`.
- `--daily-report-dir`: generated per-day supplier match summaries.
- `--top-supplier-matches`: max candidates stored per Orbika part.
- `--agentic-limit-per-part`: max candidates reviewed per part.
- `--agentic-model`: optional LLM model name; without this, review uses the local heuristic fallback.
- `--agentic-trace-dir`: generated per-quote agentic trace directory.
- `--skip-agentic-review`: skip final agentic review and persist only quote plus supplier matches.
- `--storage-state`: Playwright storage state path outside the repo.
- `--headed`: open a visible browser for local debugging.
- `--reprocess`: process already completed quote keys again.

Mode summary:

- `minimal`: keeps `state.json`, `quotes/` and `daily/`.
- `standard`: same as `minimal`, plus `agentic_traces/`.
- `debug`: same as `standard`, plus HTML `snapshots/`.

Explicit `--snapshot-dir` or `--agentic-trace-dir` paths still override the mode.

## Backfill Supplier Matching

To enrich already extracted quote JSON files with supplier matches and rebuild
daily summaries:

```bash
PYTHONPATH=. uv run python tools/supplier_quote_matcher.py
```

## Verification

Run parser and resume tests:

```bash
PYTHONPATH=. uv run python -m unittest discover -s tests -p 'test_*.py'
```

Run the repo doctor:

```bash
npm run doctor
```

## Cleanup

Use the cleanup helper in dry-run mode first:

```bash
PYTHONPATH=. uv run python tools/cleanup_incremental_outputs.py
```

Apply only after reviewing the candidate list:

```bash
PYTHONPATH=. uv run python tools/cleanup_incremental_outputs.py --apply
```

By default the helper targets:

- `agentic_traces/`, `snapshots/` and `debug/` older than 7 days
- experimental `check-*`, `backfill-*`, `phase*` and `retest-*` artifacts older than 7 days
