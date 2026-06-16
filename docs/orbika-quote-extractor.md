# Orbika Quote Extractor Phase 2

Local read-only extractor for Orbika quote pages using the `quote_url` output
from phase 1.

It is designed for quote pages that:

- may require Orbika authentication
- may load slowly or incompletely on first render
- may need the original quote URL reloaded after login
- must be processed without changing any commercial state

## Safety

- Read-only workflow only.
- No quote submission, approval, rejection or mutation.
- Do not store usernames, passwords, cookies or storage state in the repo.
- Use local environment variables for credentials:
  - `ORBIKA_USERNAME`
  - `ORBIKA_PASSWORD`
- Playwright storage state must live outside the repo.
- Full quote URLs are written only to local output files, not to logs.

## Recommended runtime

This phase uses Playwright because Orbika renders dynamic Angular content such
as `manual-purchase` and `quote-replacement`.

Install Chromium for Playwright locally if you have not done so:

```bash
uv run --with playwright python -m playwright install chromium
```

## Inputs

Use either:

- one or more `--quote-url` values
- or `--input-json local/gmail_quote_extractor/quotes.json` from phase 1

## Required local credentials

Keep credentials outside the repo, for example in a local shell-only file:

```bash
export ORBIKA_USERNAME="edordonez"
read -s ORBIKA_PASSWORD
export ORBIKA_PASSWORD
```

Do not commit or paste these values in chat.

## Run

From the repo root:

```bash
uv run \
  --with playwright \
  python tools/orbika_quote_extractor.py \
  --input-json local/gmail_quote_extractor/quotes.json \
  --json-output local/orbika_quote_extractor/orbika_quotes.json \
  --csv-output local/orbika_quote_extractor/orbika_quotes.csv
```

For local visual debugging:

```bash
uv run \
  --with playwright \
  python tools/orbika_quote_extractor.py \
  --input-json local/gmail_quote_extractor/quotes.json \
  --headed
```

## Load handling

The extractor treats a quote as ready only after the rendered page contains:

- `manual-purchase`
- `.num-aviso`
- at least one `quote-replacement`
- at least one `.tr-hd-lb`

If key data is missing, it retries with controlled refreshes. If the page is
still incomplete after retries, the record is marked as:

- `failed_after_retries`

Possible record statuses:

- `loaded`
- `partial`
- `failed_after_retries`

## Output

The JSON output includes:

- quote metadata
- vehicle data
- workshop data
- per-part extracted rows
- dynamic replacement-part fields such as reference input value, reference
  button text, validation text, validation visibility and visible DOM values
- retry count
- load status
- warnings

Optional HTML snapshots are saved under:

```text
local/orbika_quote_extractor/snapshots/
```

These snapshots are useful for debugging slow or incomplete loads locally.

## Incremental Runner

For the resumable Gmail-to-Orbika workflow, use:

```text
docs/incremental-orbika-quote-runner.md
```

That runner keeps local state, skips processed quote keys and writes one JSON
file per processed quote.

## Verification

Run parser tests:

```bash
PYTHONPATH=. uv run python -m unittest discover -s tests -p 'test_*.py'
```

Run the repo doctor:

```bash
npm run doctor
```
