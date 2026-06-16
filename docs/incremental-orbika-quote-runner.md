# Incremental Orbika Quote Runner

Local read-only runner that connects the Gmail quote-link extractor with the
Orbika quote-page extractor.

It processes new messages from `cotizacionesorbika@subocol.com`, extracts every
`quote_url`, opens each Orbika quote in a browser session, captures rendered
replacement-part data, matches each extracted part against the local supplier
catalog snapshots, and writes one independent JSON file per quote.

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

Default local outputs:

```text
local/orbika_incremental/state.json
local/orbika_incremental/quotes/<quote_key>.json
local/orbika_incremental/snapshots/<quote_key>/quote-<retry>.html
local/orbika_incremental/daily/YYYY-MM-DD.json
local/orbika_incremental/daily/YYYY-MM-DD.md
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
- `--quotes-dir`: custom per-quote JSON output directory.
- `--snapshot-dir`: custom rendered HTML snapshot directory.
- `--providers-root`: local supplier snapshot root, default `supplier_catalog/providers`.
- `--daily-report-dir`: generated per-day supplier match summaries.
- `--top-supplier-matches`: max candidates stored per Orbika part.
- `--storage-state`: Playwright storage state path outside the repo.
- `--headed`: open a visible browser for local debugging.
- `--reprocess`: process already completed quote keys again.

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
