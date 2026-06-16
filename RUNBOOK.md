# Orbika Quote Intelligence Pipeline Runbook

## Purpose

This repository contains a local, read-only pipeline for:

1. Reading Gmail messages from `cotizacionesorbika@subocol.com`.
2. Extracting Orbika external quote links from those emails.
3. Opening each Orbika quote in a browser session and extracting structured quote data.
4. Matching extracted parts against local supplier catalog snapshots.
5. Optionally running an additional heuristic or LLM-assisted agentic review on top of supplier matching.

This runbook is written for manual local operation in WSL.

## Current Repo Reality

These are the primary scripts that exist today:

- `tools/gmail_quote_extractor.py`
- `tools/orbika_quote_extractor.py`
- `tools/incremental_orbika_quote_runner.py`
- `tools/supplier_quote_matcher.py`
- `tools/agentic_match_reviewer.py`

Important current-state notes:

- There is no root `pyproject.toml`.
- There is no root `package.json`.
- Commands shown in older docs like `npm run doctor` are stale for the current repo state.
- In practice, commands should be run with `PYTHONPATH=.` from the repo root.
- Orbika login is no longer automatic by default. The extractor now tries quote URL reload recovery first. Login is available only if you pass `--allow-login-fallback`.

## Prerequisites

Recommended environment:

- WSL Ubuntu
- Python 3 available in WSL
- `uv` installed and available in PATH
- A browser that Playwright can use, or a local Playwright Chromium install

Basic checks:

```bash
python3 --version
uv --version
```

Enter the repo:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline
pwd
```

Expected output:

```text
/home/julian95/projects/Orbika-Quote-Intelligence-Pipeline
```

## Python And Node Setup

### Python / uv

This repo does not currently use a locked Python project file. Dependencies are installed ad hoc through `uv run --with ...`.

Use this pattern:

```bash
PYTHONPATH=. uv run --with <dependency> --with <dependency> python tools/<script>.py ...
```

### Node

There is no active Node startup workflow in the current repo state.

If older docs mention `npm run doctor`, treat that as outdated unless a future `package.json` is added.

## Environment Variables

### Gmail

You can provide the OAuth client path by CLI every time:

```bash
--credentials ~/.config/openclaw/gmail/autolujoslaser1-client-secret.json
```

Or via environment variable:

```bash
export GMAIL_OAUTH_CLIENT_SECRET="$HOME/.config/openclaw/gmail/autolujoslaser1-client-secret.json"
```

### Orbika

These are only needed if you intentionally allow login fallback:

```bash
export ORBIKA_USERNAME="your-username"
read -s ORBIKA_PASSWORD
export ORBIKA_PASSWORD
```

Optional Orbika debug:

```bash
export ORBIKA_DEBUG=1
export ORBIKA_DEBUG_DIR="$PWD/local/orbika_quote_extractor/debug"
```

Optional explicit browser path:

```bash
export PLAYWRIGHT_BROWSER_PATH="/usr/bin/chromium-browser"
```

### Suggested local shell helper

You can create a local shell-only file outside the repo, for example:

```bash
mkdir -p ~/.config/openclaw
chmod 700 ~/.config/openclaw
```

Example contents for a personal shell file:

```bash
export GMAIL_OAUTH_CLIENT_SECRET="$HOME/.config/openclaw/gmail/autolujoslaser1-client-secret.json"
export ORBIKA_USERNAME="your-username"
```

Then source it manually:

```bash
source ~/.config/openclaw/orbika-env.sh
read -s ORBIKA_PASSWORD
export ORBIKA_PASSWORD
```

## External Files Required

These files must exist outside the repository:

### Gmail OAuth client secret

Expected local location example:

```bash
~/.config/openclaw/gmail/autolujoslaser1-client-secret.json
```

Prepare the folder:

```bash
mkdir -p ~/.config/openclaw/gmail
chmod 700 ~/.config/openclaw/gmail
```

### Gmail OAuth token cache

Default path created automatically by the scripts:

```text
~/.cache/openclaw/gmail_quote_extractor/autolujoslaser1-token.json
```

### Playwright storage state

Default path created automatically by Orbika scripts:

```text
~/.cache/openclaw/orbika_quote_extractor/storage-state.json
```

These paths must remain outside the repo. The scripts explicitly reject repo-local secret and token paths.

## First-Time Gmail Authorization

Run the Gmail extractor once:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline

PYTHONPATH=. uv run \
  --with google-api-python-client \
  --with google-auth-oauthlib \
  python tools/gmail_quote_extractor.py \
  --credentials ~/.config/openclaw/gmail/autolujoslaser1-client-secret.json \
  --max-results 5 \
  --json-output local/gmail_quote_extractor/quotes.json
```

What should happen:

1. A browser-based Google OAuth flow opens.
2. You log in to `autolujoslaser1@gmail.com`.
3. You approve Gmail read-only access.
4. The token cache is written locally.

## Validate That The OAuth Token Was Created

Check the folder:

```bash
ls -la ~/.cache/openclaw/gmail_quote_extractor
```

Check the token file:

```bash
ls -l ~/.cache/openclaw/gmail_quote_extractor/autolujoslaser1-token.json
```

If the file exists, Gmail authorization was stored.

## Install Playwright Browser

Before running Orbika extraction, install Chromium for Playwright:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline

PYTHONPATH=. uv run \
  --with playwright \
  python -m playwright install chromium
```

## Phase 1: Gmail Quote Link Extraction

Run once:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline

PYTHONPATH=. uv run \
  --with google-api-python-client \
  --with google-auth-oauthlib \
  python tools/gmail_quote_extractor.py \
  --credentials ~/.config/openclaw/gmail/autolujoslaser1-client-secret.json \
  --max-results 25 \
  --json-output local/gmail_quote_extractor/quotes.json
```

Optional CSV:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline

PYTHONPATH=. uv run \
  --with google-api-python-client \
  --with google-auth-oauthlib \
  python tools/gmail_quote_extractor.py \
  --credentials ~/.config/openclaw/gmail/autolujoslaser1-client-secret.json \
  --max-results 25 \
  --json-output local/gmail_quote_extractor/quotes.json \
  --csv-output local/gmail_quote_extractor/quotes.csv
```

## Phase 2: Orbika Quote Extraction

Process the output of phase 1:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline

PYTHONPATH=. uv run \
  --with playwright \
  python tools/orbika_quote_extractor.py \
  --input-json local/gmail_quote_extractor/quotes.json \
  --json-output local/orbika_quote_extractor/orbika_quotes.json \
  --csv-output local/orbika_quote_extractor/orbika_quotes.csv
```

Visual debugging:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline

PYTHONPATH=. uv run \
  --with playwright \
  python tools/orbika_quote_extractor.py \
  --input-json local/gmail_quote_extractor/quotes.json \
  --headed
```

Important current behavior:

- By default, this script does not automatically log in to Orbika.
- It first tries to recover the quote by reopening and reloading the original quote URL.
- Only use `--allow-login-fallback` if you intentionally want Orbika username/password login as a fallback path.

Login fallback example:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline

PYTHONPATH=. uv run \
  --with playwright \
  python tools/orbika_quote_extractor.py \
  --input-json local/gmail_quote_extractor/quotes.json \
  --allow-login-fallback \
  --headed
```

## Full Incremental Pipeline

This is the main end-to-end local workflow. It reads Gmail, opens Orbika, extracts the quote, matches suppliers, and writes one JSON per quote.

### One-Time Run

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline

PYTHONPATH=. uv run \
  --with google-api-python-client \
  --with google-auth-oauthlib \
  --with playwright \
  python tools/incremental_orbika_quote_runner.py \
  --credentials ~/.config/openclaw/gmail/autolujoslaser1-client-secret.json \
  --max-results 50
```

### One-Time Run For A Specific Day

The runner now supports Gmail day filtering:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline

PYTHONPATH=. uv run \
  --with google-api-python-client \
  --with google-auth-oauthlib \
  --with playwright \
  python tools/incremental_orbika_quote_runner.py \
  --credentials ~/.config/openclaw/gmail/autolujoslaser1-client-secret.json \
  --gmail-date 2026-06-14 \
  --max-results 50
```

With visible browser:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline

PYTHONPATH=. uv run \
  --with google-api-python-client \
  --with google-auth-oauthlib \
  --with playwright \
  python tools/incremental_orbika_quote_runner.py \
  --credentials ~/.config/openclaw/gmail/autolujoslaser1-client-secret.json \
  --gmail-date 2026-06-14 \
  --max-results 50 \
  --headed
```

If you explicitly want Orbika login fallback enabled:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline

PYTHONPATH=. uv run \
  --with google-api-python-client \
  --with google-auth-oauthlib \
  --with playwright \
  python tools/incremental_orbika_quote_runner.py \
  --credentials ~/.config/openclaw/gmail/autolujoslaser1-client-secret.json \
  --gmail-date 2026-06-14 \
  --max-results 50 \
  --allow-login-fallback
```

### Continuous Polling For New Emails

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline

PYTHONPATH=. uv run \
  --with google-api-python-client \
  --with google-auth-oauthlib \
  --with playwright \
  python tools/incremental_orbika_quote_runner.py \
  --credentials ~/.config/openclaw/gmail/autolujoslaser1-client-secret.json \
  --max-results 50 \
  --poll-seconds 300
```

Stop with `Ctrl+C`.

## Supplier Matching

The incremental runner already runs matching during normal processing.

Use this script when you want to backfill or rebuild matching for quotes already saved on disk:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline

PYTHONPATH=. uv run \
  python tools/supplier_quote_matcher.py
```

With explicit options:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline

PYTHONPATH=. uv run \
  python tools/supplier_quote_matcher.py \
  --quotes-dir local/orbika_incremental/quotes \
  --providers-root supplier_catalog/providers \
  --daily-report-dir local/orbika_incremental/daily \
  --limit-per-part 5
```

## Agentic Review

### Heuristic Agentic Review

This mode works without OpenAI credentials.

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline

PYTHONPATH=. uv run \
  python tools/agentic_match_reviewer.py
```

With explicit options:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline

PYTHONPATH=. uv run \
  python tools/agentic_match_reviewer.py \
  --quotes-dir local/orbika_incremental/quotes \
  --trace-dir local/orbika_incremental/agentic_traces \
  --limit-per-part 5
```

Disable trace files:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline

PYTHONPATH=. uv run \
  python tools/agentic_match_reviewer.py \
  --disable-traces
```

### LLM-Assisted Agentic Review

This mode only activates if:

- `OPENAI_API_KEY` is set
- the optional LangChain dependencies are available
- `--model` is passed

Example:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline

PYTHONPATH=. uv run \
  --with langchain \
  --with langchain-openai \
  --with langgraph \
  python tools/agentic_match_reviewer.py \
  --model gpt-4.1-mini
```

If those optional dependencies are missing, the script falls back to heuristic mode.

## Outputs

### Gmail extractor

```text
local/gmail_quote_extractor/quotes.json
local/gmail_quote_extractor/quotes.csv
```

### Orbika extractor

```text
local/orbika_quote_extractor/orbika_quotes.json
local/orbika_quote_extractor/orbika_quotes.csv
local/orbika_quote_extractor/snapshots/
local/orbika_quote_extractor/debug/
```

### Incremental runner

```text
local/orbika_incremental/state.json
local/orbika_incremental/quotes/<quote_key>.json
local/orbika_incremental/snapshots/<quote_key>/quote-<retry>.html
local/orbika_incremental/daily/YYYY-MM-DD.json
local/orbika_incremental/daily/YYYY-MM-DD.md
local/orbika_incremental/agentic_traces/<quote_key>.agentic_trace.json
```

### Supplier catalogs

Provider snapshots live under:

```text
supplier_catalog/providers/<provider_id>/snapshots/YYYY-MM-DD/
```

## Common Problems And Fixes

### `can't open file '/home/julian95/tools/incremental_orbika_quote_runner.py'`

Cause:

- You ran the command from `~` instead of the repo root.

Fix:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline
pwd
```

### `ModuleNotFoundError: No module named 'tools'`

Cause:

- Python was not started with the repo root in `PYTHONPATH`.

Fix:

Always run scripts like this:

```bash
PYTHONPATH=. uv run ...
```

### `google.auth.exceptions.RefreshError: invalid_grant`

Cause:

- The Gmail OAuth token expired or was revoked.

Fix:

```bash
rm -f ~/.cache/openclaw/gmail_quote_extractor/autolujoslaser1-token.json
```

Then rerun a Gmail-based command to authorize again.

### Authenticated with the wrong Gmail account

Cause:

- The OAuth browser flow used an account different from `autolujoslaser1@gmail.com`.

Fix:

- Re-run authorization and choose the correct account.
- The script already verifies the account and will stop if it is wrong.

### Playwright browser missing

Symptoms:

- Playwright starts but Chromium is not installed.

Fix:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline

PYTHONPATH=. uv run \
  --with playwright \
  python -m playwright install chromium
```

### Orbika quote does not load and lands in login or marketplace

Current behavior:

- The extractor first retries the original quote URL and reloads the page.
- Login is not automatic by default.

What to do:

- Retry with `--headed` so you can watch the browser.
- Only add `--allow-login-fallback` if reload recovery is truly not enough.

### Orbika account lock risk

Context:

- Repeated automatic login attempts may contribute to account lockouts.

Current mitigation:

- The extractor now avoids automatic login unless `--allow-login-fallback` is passed.

### `.zshrc: command not found: pyenv`

Cause:

- Your shell startup references `pyenv`, but `pyenv` is not installed.

Impact:

- Usually harmless for this project if `python3` and `uv` still work.

Fix options:

- Install `pyenv`, or
- remove/comment those lines in `~/.zshrc`

### `npm run doctor`

Current status:

- Older docs mention it, but the current repo has no root `package.json`.
- Do not rely on `npm run doctor` unless the repo gains a Node manifest later.

## Validation Commands

Run targeted tests:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline

python3 -m unittest tests.test_gmail_quote_extractor
python3 -m unittest tests.test_orbika_quote_extractor
python3 -m unittest tests.test_incremental_orbika_quote_runner
python3 -m unittest tests.test_supplier_quote_matcher
python3 -m unittest tests.test_agentic_match_reviewer
```

Or run the whole suite:

```bash
cd /home/julian95/projects/Orbika-Quote-Intelligence-Pipeline

PYTHONPATH=. uv run python -m unittest discover -s tests -p 'test_*.py'
```

## Documentation Drift Notes

These existing docs are still useful for context but are partially outdated:

- `docs/gmail-quote-extractor.md`
- `docs/orbika-quote-extractor.md`
- `docs/incremental-orbika-quote-runner.md`

Main differences versus current code:

- They do not consistently show `PYTHONPATH=.`
- They still imply older Orbika login expectations
- They do not mention `--gmail-date`
- They still mention `npm run doctor`, which is not currently backed by a root Node manifest

Use this runbook as the operational source of truth for the current repo state.
