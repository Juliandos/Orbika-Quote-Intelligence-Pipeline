# Orbika Extraction Executive Report

## Objective
Document the end-to-end project that extracts Orbika quotation data from Gmail, opens the quote URL, handles Orbika login and redirects, and stores structured outputs in a restartable incremental workflow.

## Executive Summary
The extraction project reached a working state in phases. Phase 1 now extracts quote URLs from Gmail messages sent by `cotizacionesorbika@subocol.com`. Phase 2 can open Orbika, authenticate when needed, return to the original quote URL, and extract structured quotation data. A third incremental layer persists progress and allows the worker to resume after interruption.

The project is functionally solid, but it was also shaped by repeated operational friction in OpenClaw: partial task execution, ambiguous task states, Telegram command misrouting, and dashboard actions that sometimes recorded intent more than actual execution. Those issues slowed iteration and made the extraction pipeline harder to validate than it should have been.
 
## What Was Built
- `tools/gmail_quote_extractor.py`
- `tools/orbika_quote_extractor.py`
- `tools/incremental_orbika_quote_runner.py`
- Tests for parser, Orbika extraction, and incremental resume behavior.
- Documentation for the Gmail extractor, Orbika extractor, and incremental runner.
- Local state and output directories for per-quote persistence.

## Current Functional Flow
1. Read Gmail in readonly mode.
2. Filter messages from `cotizacionesorbika@subocol.com`.
3. Extract the real `quote_url` from the email.
4. Open Orbika with Playwright.
5. If Orbika redirects to login, authenticate locally and return to the original `quote_url`.
6. If Orbika redirects to dashboard, role selection, marketplace, or permissions screens, reload the original `quote_url`.
7. If the quote opens empty or partially rendered, wait and retry.
8. Parse the rendered quotation data and write one JSON file per quote.
9. Persist progress so the worker can resume without duplicating work.

## What Works Well
- Gmail readonly OAuth is working.
- Quote links are being extracted reliably from emails.
- Orbika login can be handled from the local browser flow.
- The extractor can recover from common redirects and return to the original quote URL.
- The parser now captures the key vehicle and workshop fields more accurately.
- The incremental runner stores state and quote outputs independently.

## Where the Project Was Initially Weak
- Some early parsing logic interpreted decorative UI text as data.
- Empty or partial quotes were sometimes misclassified.
- Dashboard and marketplace detours caused the first implementation to appear broken even when the quote eventually loaded.
- OpenClaw task execution was frequently partial, which made it hard to distinguish between “code exists” and “workflow actually works”.

## How OpenClaw Affected This Project
The extraction project exposed the weakest parts of OpenClaw:
- Telegram did not always respect long context updates.
- Some messages were treated as status or heartbeat requests instead of instructions.
- The dashboard execution and verification flow was not always equivalent to a real code run.
- Partial task packets sometimes looked more advanced than the actual implementation.

These limitations forced the work to be validated manually, first in WSL and then against real Gmail and Orbika behavior.

## Operational Learnings
- The worker should remain idle until a new relevant email arrives.
- The system should always reload the original `quote_url` after login or role selection.
- A quote that is present but empty should be retried, not immediately treated as a final failure.
- Each processed quotation should get its own output file.
- A local state file is essential so a restart does not lose progress.

## Business Value
The project reduces manual work by:
- turning incoming quotations into structured data,
- preserving traceability per email and per quote,
- allowing restarts without losing the processing point,
- and supporting future automation around quote monitoring and follow-up.

## Bottom Line
The Orbika extraction pipeline is now a real local automation system, not just a one-off script. Its biggest technical risk is no longer the extraction logic itself; it is the operational discipline around long-running execution, task coordination, and reliable operator feedback inside OpenClaw.
