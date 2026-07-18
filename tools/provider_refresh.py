#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.postgres_quote_persistence import database_url_from_env, persist_quote_files

UV_CANDIDATES = [REPO_ROOT / ".venv/bin/uv", Path.home() / ".local/bin/uv"]
UV_BIN = next((candidate for candidate in UV_CANDIDATES if candidate.exists()), Path("uv"))
CATALOG_EXTRACTOR_SCRIPTS = [
    ("autolatas", "tools/autolatas_catalog_extractor.py"),
    ("autopartesercar", "tools/autopartesercar_catalog_extractor.py"),
    ("autopartesya", "tools/autopartesya_catalog_extractor.py"),
    ("autorecambiosltda", "tools/autorecambiosltda_catalog_extractor.py"),
    ("corbeta", "tools/corbeta_catalog_extractor.py"),
    ("disfal", "tools/disfal_catalog_extractor.py"),
    ("exaap", "tools/exaap_catalog_extractor.py"),
    ("fanauto", "tools/fanauto_catalog_extractor.py"),
    ("imotriz", "tools/imotriz_catalog_extractor.py"),
    ("imotrizsolucionesautomotrices", "tools/imotrizsolucionesautomotrices_catalog_extractor_scroll.py"),
    ("impocali", "tools/impocali_catalog_extractor.py"),
    ("importadoraeurobrasil", "tools/importadoraeurobrasil_catalog_extractor.py"),
    ("importadorasasociadas", "tools/importadorasasociadas_catalog_extractor.py"),
    ("internacionaldepartes", "tools/internacionaldepartes_catalog_extractor.py"),
    ("latiendadelrepuesto", "tools/latiendadelrepuesto_catalog_extractor.py"),
    ("motorpartes", "tools/motorpartes_catalog_extractor.py"),
    ("parrales", "tools/parrales_catalog_extractor.py"),
    ("partcar", "tools/partcar_catalog_extractor.py"),
    ("pintuco", "tools/pintuco_catalog_extractor.py"),
    ("ppaautomotriz", "tools/ppaautomotriz_catalog_extractor.py"),
    ("procar", "tools/procar_catalog_extractor.py"),
    ("propartes", "tools/propartes_catalog_extractor.py"),
    ("redpuestos", "tools/redpuestos_catalog_extractor.py"),
    ("repuestera", "tools/repuestera_catalog_extractor.py"),
    ("totus", "tools/totus_catalog_extractor.py"),
    ("tusautopartes", "tools/tusautopartes_catalog_extractor.py"),
    ("universaldepartes", "tools/universaldepartes_catalog_extractor.py"),
    ("ventarepuestosmayor", "tools/ventarepuestosmayor_catalog_extractor.py"),
    ("yamatocolombia", "tools/yamatocolombia_catalog_extractor.py"),
]
CATALOG_INGEST_SCRIPT = "tools/provider_catalog_ingest.py"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_step(name: str, command: list[str]) -> dict[str, Any]:
    started = time.time()
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        env=dict(os.environ, PYTHONPATH="."),
    )
    if completed.stdout:
        print(completed.stdout.rstrip())
    if completed.stderr:
        print(completed.stderr.rstrip(), file=sys.stderr)
    return {
        "name": name,
        "status": "completed" if completed.returncode == 0 else "failed",
        "command": command,
        "returncode": completed.returncode,
        "started_at": started,
        "finished_at": time.time(),
        "duration_seconds": round(time.time() - started, 2),
        "stdout_tail": (completed.stdout or "")[-4000:],
        "stderr_tail": (completed.stderr or "")[-4000:],
    }


def build_report(*, quotes_dir: Path, limit_per_part: int, trace_dir: Path | None, database_url: str | None) -> dict[str, Any]:
    quote_files = sorted(quotes_dir.glob("*.json"))
    report: dict[str, Any] = {
        "status": "starting",
        "generated_at": utc_now_iso(),
        "limit_per_part": limit_per_part,
        "quotes_dir": str(quotes_dir),
        "provider_extraction": {"status": "not_run", "providers": []},
        "catalog_ingest": {"status": "not_run"},
        "matching": {"status": "not_run"},
        "agentic_review": {"status": "not_run"},
        "postgres_sync": {"enabled": bool(database_url), "status": "not_run"},
        "summary": {
            "quotes_seen": len(quote_files),
            "quotes_with_provider": 0,
            "quotes_with_agentic": 0,
        },
        "message": "El refresco semanal todavia no termina.",
    }
    if trace_dir is not None:
        report["trace_dir"] = str(trace_dir)
    return report


def read_summary_from_quotes(quotes_dir: Path) -> dict[str, int]:
    quotes_with_provider = 0
    quotes_with_agentic = 0
    for path in quotes_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        matching_summary = payload.get("supplier_matching", {}).get("summary", {})
        agentic_summary = payload.get("agentic_supplier_matching", {}).get("summary", {})
        if (matching_summary.get("parts_with_matches") or 0) > 0:
            quotes_with_provider += 1
        if (agentic_summary.get("parts_with_agentic_matches") or 0) > 0:
            quotes_with_agentic += 1
    return {
        "quotes_with_provider": quotes_with_provider,
        "quotes_with_agentic": quotes_with_agentic,
    }


def run_catalog_extractors() -> dict[str, Any]:
    provider_results: list[dict[str, Any]] = []
    failed = 0
    for provider_id, script_path in CATALOG_EXTRACTOR_SCRIPTS:
        command = [str(UV_BIN), "run", "--with", "playwright", "python", script_path]
        step = run_step(
            f"catalog_extractor:{provider_id}",
            command,
        )
        step["provider_id"] = provider_id
        provider_results.append(step)
        if step["status"] != "completed":
            failed += 1
    return {
        "status": "completed" if failed == 0 else "completed_with_failures",
        "providers": provider_results,
        "summary": {
            "providers_total": len(provider_results),
            "providers_completed": len(provider_results) - failed,
            "providers_failed": failed,
        },
        "message": (
            "Todos los extractores vivos terminaron correctamente."
            if failed == 0
            else "Algunos extractores vivos fallaron; el refresco continuara usando snapshots disponibles."
        ),
    }


def run_catalog_ingestion(database_url: str | None) -> dict[str, Any]:
    if not database_url:
        return {
            "status": "skipped",
            "message": "No hay DATABASE_URL configurado; el catalogo no se sincronizo a PostgreSQL.",
        }
    command = [str(UV_BIN), "run", "python", CATALOG_INGEST_SCRIPT]
    step = run_step("provider_catalog_ingest", command)
    return {
        "status": step["status"],
        "command": step["command"],
        "returncode": step["returncode"],
        "stdout_tail": step["stdout_tail"],
        "stderr_tail": step["stderr_tail"],
    }


def provider_refresh(
    *,
    quotes_dir: Path,
    daily_report_dir: Path,
    trace_dir: Path,
    report_file: Path,
    limit_per_part: int,
) -> dict[str, Any]:
    database_url = database_url_from_env()
    report = build_report(quotes_dir=quotes_dir, limit_per_part=limit_per_part, trace_dir=trace_dir, database_url=database_url)
    report_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        report["provider_extraction"] = run_catalog_extractors()
        report["catalog_ingest"] = run_catalog_ingestion(database_url)

        matching_command = [
            str(UV_BIN),
            "run",
            "python",
            "tools/supplier_quote_matcher.py",
            "--quotes-dir",
            str(quotes_dir),
            "--daily-report-dir",
            str(daily_report_dir),
            "--limit-per-part",
            str(limit_per_part),
        ]
        report["matching"] = run_step("supplier_matching", matching_command)
        if report["matching"]["status"] != "completed":
            raise RuntimeError("El matching de proveedores fallo durante el refresco semanal.")

        agentic_command = [
            str(UV_BIN),
            "run",
            "python",
            "tools/agentic_match_reviewer.py",
            "--quotes-dir",
            str(quotes_dir),
            "--limit-per-part",
            str(limit_per_part),
            "--disable-traces",
        ]
        report["agentic_review"] = run_step("agentic_review", agentic_command)
        if report["agentic_review"]["status"] != "completed":
            raise RuntimeError("La revision IA fallo durante el refresco semanal.")

        quote_files = sorted(quotes_dir.glob("*.json"))
        if database_url:
            counters = persist_quote_files(quote_files, database_url=database_url, dry_run=False)
            report["postgres_sync"] = {
                "enabled": True,
                "status": "completed" if counters.failed == 0 else "failed",
                "files": len(quote_files),
                "imported": counters.imported,
                "updated": counters.updated,
                "skipped": counters.skipped,
                "failed": counters.failed,
            }
            if counters.failed:
                raise RuntimeError("La sincronizacion PostgreSQL del refresco semanal termino con errores.")
        else:
            report["postgres_sync"] = {
                "enabled": False,
                "status": "skipped",
                "message": "No hay DATABASE_URL configurado; el refresco solo actualizo archivos locales.",
            }

        report["summary"].update(read_summary_from_quotes(quotes_dir))
        extraction_failed = (
            report.get("provider_extraction", {})
            .get("summary", {})
            .get("providers_failed", 0)
        )
        if extraction_failed:
            report["status"] = "completed_with_warnings"
            report["message"] = (
                "El matching termino usando snapshots disponibles, pero "
                f"{extraction_failed} extractor(es) fallaron y requieren revision."
            )
        elif report.get("catalog_ingest", {}).get("status") != "completed":
            report["status"] = "completed_with_warnings"
            report["message"] = (
                "El refresco termino correctamente, pero la sincronizacion del catalogo a PostgreSQL "
                "presento advertencias."
            )
        else:
            report["status"] = "completed"
            report["message"] = "El refresco semanal de proveedores termino correctamente."
    except Exception as exc:  # noqa: BLE001
        report["status"] = "failed"
        report["message"] = str(exc)
    finally:
        report["generated_at"] = utc_now_iso()
        report_file.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")

    if report["status"] not in {"completed", "completed_with_warnings"}:
        raise SystemExit(1)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Weekly provider refresh for Orbika local operation.")
    parser.add_argument("--quotes-dir", type=Path, required=True)
    parser.add_argument("--daily-report-dir", type=Path, required=True)
    parser.add_argument("--trace-dir", type=Path, required=True)
    parser.add_argument("--report-file", type=Path, required=True)
    parser.add_argument("--limit-per-part", type=int, default=5)
    args = parser.parse_args(argv)

    report = provider_refresh(
        quotes_dir=args.quotes_dir,
        daily_report_dir=args.daily_report_dir,
        trace_dir=args.trace_dir,
        report_file=args.report_file,
        limit_per_part=args.limit_per_part,
    )
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
