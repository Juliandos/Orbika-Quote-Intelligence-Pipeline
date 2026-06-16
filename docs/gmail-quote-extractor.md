# Gmail Quote Extractor Phase 1

Local read-only extractor for the authorized Gmail account
`autolujoslaser1@gmail.com`.

It reads only messages from `cotizacionesorbika@subocol.com`, parses the email
HTML first, finds the visible link text `Cotizar aviso`, and writes structured
local output with the real `href`.

## Safety

- Gmail scope: `https://www.googleapis.com/auth/gmail.readonly`
- No replies, forwards, archive, delete, label or mutation calls.
- Attachments are not downloaded.
- OAuth client secrets and token cache must be outside this repository.
- Full quote URLs are written only to the local output file, not printed in logs.
- Default output path is `local/gmail_quote_extractor/quotes.json`, which is
  ignored by Git.

The observed Gmail UI selector is retained only as a manual fallback reference:

```text
#avWBGd-182 > div:nth-child(2) > div:nth-child(1) > div:nth-child(3) > table > tbody > tr > td > div > table > tbody > tr > td > table > tbody > tr > td > a
```

Phase 1 does not automate the Gmail browser UI; it prefers the message HTML.

## Setup

The parser tests do not need Gmail API dependencies. The real Gmail run uses
temporary `uv` dependencies through `--with`, so `pyproject.toml` and `uv.lock`
stay unchanged until this extractor graduates from phase 1.

Check that `uv` is available:

```bash
uv --version
```

Place the OAuth client secret JSON outside the repo, for example:

```bash
mkdir -p ~/.config/openclaw/gmail
chmod 700 ~/.config/openclaw/gmail
```

Then put the client secret file in that directory. Do not commit it and do not
copy it into this repository.

## Run

```bash
uv run \
  --with google-api-python-client \
  --with google-auth-oauthlib \
  python tools/gmail_quote_extractor.py \
  --credentials ~/.config/openclaw/gmail/autolujoslaser1-client-secret.json \
  --max-results 25 \
  --json-output local/gmail_quote_extractor/quotes.json
```

Optional CSV output:

```bash
uv run \
  --with google-api-python-client \
  --with google-auth-oauthlib \
  python tools/gmail_quote_extractor.py \
  --credentials ~/.config/openclaw/gmail/autolujoslaser1-client-secret.json \
  --json-output local/gmail_quote_extractor/quotes.json \
  --csv-output local/gmail_quote_extractor/quotes.csv
```

The OAuth token cache defaults to:

```text
~/.cache/openclaw/gmail_quote_extractor/autolujoslaser1-token.json
```

The script rejects credential and token-cache paths that are inside the repo.

## Output Shape

The JSON output includes:

- `message_id`
- `sender`
- `subject`
- `received_at`
- `quote_url`
- `audit_excerpt`
- `extraction_status`
- `warnings`

Expected statuses:

- `extracted`
- `link_not_found`
- `sender_mismatch`

## Verification

Run parser tests:

```bash
PYTHONPATH=. uv run python -m unittest discover -s tests -p 'test_*.py'
```

Run the repo doctor:

```bash
npm run doctor
```
