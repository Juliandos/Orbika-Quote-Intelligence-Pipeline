from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
LOCAL_DIR = REPO_ROOT / "local"
INCREMENTAL_DIR = LOCAL_DIR / "orbika_incremental"
QUOTES_DIR = INCREMENTAL_DIR / "quotes"
STATE_PATH = INCREMENTAL_DIR / "state.json"
SNAPSHOTS_DIR = INCREMENTAL_DIR / "snapshots"
DAILY_DIR = INCREMENTAL_DIR / "daily"
AGENTIC_TRACES_DIR = INCREMENTAL_DIR / "agentic_traces"
TASK_LOG_DIR = LOCAL_DIR / "console_api"
TASK_LOG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_GMAIL_CREDENTIALS = os.environ.get(
    "GMAIL_OAUTH_CLIENT_SECRET",
    str(Path.home() / ".config" / "openclaw" / "gmail" / "autolujoslaser1-client-secret.json"),
)
DEFAULT_GMAIL_TOKEN_CACHE = str(
    Path.home() / ".cache" / "openclaw" / "gmail_quote_extractor" / "autolujoslaser1-token.json"
)
DEFAULT_ORBIKA_STORAGE_STATE = str(
    Path.home() / ".cache" / "openclaw" / "orbika_quote_extractor" / "storage-state.json"
)

FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")
