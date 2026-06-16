#!/usr/bin/env python3
"""Read-only Orbika quotation extractor for quote URLs from phase 1."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


DEFAULT_OUTPUT_DIR = Path("local/orbika_quote_extractor")
DEFAULT_STORAGE_STATE = (
    Path.home()
    / ".cache"
    / "openclaw"
    / "orbika_quote_extractor"
    / "storage-state.json"
)
DEFAULT_HTML_SNAPSHOT_DIR = DEFAULT_OUTPUT_DIR / "snapshots"
DEFAULT_DEBUG_DIR = DEFAULT_OUTPUT_DIR / "debug"
ORBika_USERNAME_ENV = "ORBIKA_USERNAME"
ORBika_PASSWORD_ENV = "ORBIKA_PASSWORD"
ORBIKA_DEBUG_ENV = "ORBIKA_DEBUG"
ORBIKA_DEBUG_DIR_ENV = "ORBIKA_DEBUG_DIR"
PLAYWRIGHT_BROWSER_PATH_ENV = "PLAYWRIGHT_BROWSER_PATH"
QUOTE_READY_SELECTORS = [
    "manual-purchase",
    ".num-aviso",
    "quote-replacement",
    ".tr-hd-lb",
]
QUOTE_SHELL_SELECTORS = [
    "manual-purchase",
    ".div-info-aviso",
    ".div-contentAviso",
    ".div-down",
    "#footer-quote",
]
LOGIN_HINT_SELECTORS = [
    "input[type='password']",
    "input[name='password']",
    "input[name='username']",
    "input[name='login']",
    "input[name*='_username']",
    "input[name*='_password']",
]
TEXT_LABELS = {
    "marca": "Marca:",
    "linea": "Línea:",
    "version": "Versión:",
    "ano": "Año:",
    "placa": "Placa:",
    "vin": "VIN:",
    "nombre_comercial": "Nombre comercial:",
    "nit": "Nit:",
    "ciudad": "Ciudad:",
    "direccion": "Dirección:",
    "telefono": "Teléfono:",
    "email": "E-mail:",
}


@dataclass
class ExtractedPart:
    name: str
    reference: str | None
    reference_input_value: str | None
    reference_button_text: str | None
    reference_source: str | None
    reference_validation_text: str | None
    reference_validation_visible: bool
    quantity: int | None
    unit_gross_price: str | None
    delivery_days: str | None
    discount: str | None
    quality: str | None
    total_value: str | None
    observation_visible: str | None
    rejected_button_present: bool
    raw_status: str
    visible_dom_values: dict[str, str | None] = field(default_factory=dict)


@dataclass
class ExtractedQuote:
    quote_url: str
    load_status: str
    retries_used: int
    aviso_id: str | None
    fecha_aviso: str | None
    marca: str | None
    linea: str | None
    version: str | None
    ano: str | None
    placa: str | None
    vin: str | None
    taller_entrega: str | None
    nombre_comercial: str | None
    nit: str | None
    ciudad: str | None
    direccion: str | None
    telefono: str | None
    email: str | None
    repuestos_count: int
    total_cotizacion: str | None
    repuestos_cotizados: str | None
    parts: list[ExtractedPart] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class DebugRecorder:
    def __init__(self, enabled: bool, run_dir: Path | None) -> None:
        self.enabled = enabled
        self.run_dir = run_dir
        self.event_index = 0
        self.snapshot_index = 0
        self.log_path = run_dir / "trace.log" if run_dir else None

    def log(self, message: str, **fields: Any) -> None:
        if not self.enabled or not self.log_path:
            return
        self.event_index += 1
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        rendered_fields = " ".join(
            f"{key}={json.dumps(value, ensure_ascii=False)}"
            for key, value in fields.items()
        )
        line = f"[{timestamp}] #{self.event_index:03d} {message}"
        if rendered_fields:
            line = f"{line} {rendered_fields}"
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def snapshot(self, label: str, html: str, current_url: str | None = None) -> Path | None:
        if not self.enabled or not self.run_dir:
            return None
        self.snapshot_index += 1
        safe_label = re.sub(r"[^a-z0-9._-]+", "-", label.lower()).strip("-") or "snapshot"
        snapshot_path = self.run_dir / f"{self.snapshot_index:03d}-{safe_label}.html"
        snapshot_path.write_text(html, encoding="utf-8")
        self.log(
            "snapshot_saved",
            label=label,
            path=str(snapshot_path),
            current_url=mask_url(current_url or ""),
        )
        return snapshot_path


def env_flag_is_true(name: str) -> bool:
    value = os.environ.get(name, "").strip().lower()
    return value in {"1", "true", "yes", "on", "debug"}


def build_debug_recorder() -> DebugRecorder:
    if not env_flag_is_true(ORBIKA_DEBUG_ENV):
        return DebugRecorder(enabled=False, run_dir=None)
    root = Path(os.environ.get(ORBIKA_DEBUG_DIR_ENV, str(DEFAULT_DEBUG_DIR))).expanduser()
    run_dir = root / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    run_dir.mkdir(parents=True, exist_ok=True)
    recorder = DebugRecorder(enabled=True, run_dir=run_dir)
    recorder.log("debug_enabled", run_dir=str(run_dir))
    return recorder


def normalize_text(value: str) -> str:
    text = unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def collapse_html(value: str) -> str:
    return re.sub(r"\s+", " ", value)


def html_attr(attrs: str, name: str) -> str | None:
    match = re.search(
        rf"""\b{re.escape(name)}\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""",
        attrs,
        re.IGNORECASE,
    )
    if not match:
        return None
    return normalize_text(next(group for group in match.groups() if group is not None))


def html_tag_is_visible(attrs: str) -> bool:
    style = (html_attr(attrs, "style") or "").lower()
    aria_hidden = (html_attr(attrs, "aria-hidden") or "").lower()
    hidden_attr = re.search(r"\bhidden\b", attrs, re.IGNORECASE) is not None
    return not hidden_attr and aria_hidden != "true" and "display:none" not in style.replace(" ", "")


def section_after_title(compact_block: str, title: str) -> str:
    match = re.search(
        rf"{re.escape(title)}\s*</span>(.*?)(?=<span[^>]*class=(?:\"|')[^\"']*tr-tituloInput|</quote-replacement>|\Z)",
        compact_block,
        re.IGNORECASE,
    )
    return match.group(1) if match else ""


def is_path_inside_repo(path: Path, repo_root: Path) -> bool:
    try:
        path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return False
    return True


def reject_repo_secret_path(path: Path, repo_root: Path, label: str) -> None:
    if is_path_inside_repo(path.expanduser(), repo_root):
        raise SystemExit(
            f"{label} must not be stored inside the repository: {path}. "
            "Use a path outside the repo, for example under ~/.config or ~/.cache."
        )


def mask_url(value: str) -> str:
    parts = urlsplit(value)
    if not parts.query:
        return value
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "<redacted>", parts.fragment))


def quotes_from_phase1_json(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records", [])
    quote_urls = []
    for record in records:
        if record.get("extraction_status") != "extracted":
            continue
        quote_url = str(record.get("quote_url") or "").strip()
        if quote_url:
            quote_urls.append(quote_url)
    return quote_urls


def extract_text_by_label(compact_html: str, label: str) -> str | None:
    pattern = re.compile(
        rf"{re.escape(label)}\s*</span>\s*(?:<div[^>]*>\s*)?<span[^>]*(?:class=\"[^\"]*valor-dato[^\"]*\")?[^>]*>(.*?)</span>",
        re.IGNORECASE,
    )
    match = pattern.search(compact_html)
    if match:
        return normalize_text(match.group(1))
    return None


def extract_notice_id(compact_html: str) -> str | None:
    match = re.search(r'class="num-aviso">\s*([^<]+)\s*</span>', compact_html, re.IGNORECASE)
    return normalize_text(match.group(1)) if match else None


def extract_notice_date(compact_html: str) -> str | None:
    match = re.search(r'class="fecha-aviso">\s*([^<]+)\s*</span>', compact_html, re.IGNORECASE)
    return normalize_text(match.group(1)) if match else None


def extract_delivery_workshop(compact_html: str) -> str | None:
    match = re.search(r'class="nombre-taller">\s*([^<]+)\s*</span>', compact_html, re.IGNORECASE)
    return normalize_text(match.group(1)) if match else None


def extract_footer_summary(compact_html: str) -> tuple[str | None, str | None]:
    quoted_match = re.search(
        r"Repuestos cotizados</span>\s*<span[^>]*>\s*([^<]+)\s*</span>",
        compact_html,
        re.IGNORECASE,
    )
    total_match = re.search(
        r"Total cotización</span>\s*<span[^>]*>\s*([^<]+)\s*</span>",
        compact_html,
        re.IGNORECASE,
    )
    return (
        normalize_text(quoted_match.group(1)) if quoted_match else None,
        normalize_text(total_match.group(1)) if total_match else None,
    )


def split_part_blocks(html: str) -> list[str]:
    return re.findall(
        r"<quote-replacement\b.*?</quote-replacement>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )


def extract_part_name(compact_block: str) -> str | None:
    match = re.search(
        r'<label[^>]*class="[^"]*tr-hd-lb[^"]*"[^>]*>\s*([^<]+)\s*</label>',
        compact_block,
        re.IGNORECASE,
    )
    return normalize_text(match.group(1)) if match else None


def extract_input_value_after_title(compact_block: str, title: str, id_prefix: str | None = None) -> str | None:
    section = section_after_title(compact_block, title)
    for input_match in re.finditer(r"<input\b([^>]*)>", section, re.IGNORECASE):
        attrs = input_match.group(1)
        input_id = html_attr(attrs, "id") or ""
        if id_prefix and not input_id.startswith(id_prefix):
            continue
        candidate = normalize_text(html_attr(attrs, "value") or "")
        return candidate or None
    return None


def extract_button_text_after_title(compact_block: str, title: str) -> str | None:
    section = section_after_title(compact_block, title)
    button_match = re.search(r"<button\b[^>]*>(.*?)</button>", section, re.IGNORECASE)
    if button_match:
        candidate = normalize_text(button_match.group(1))
        return candidate or None
    return None


def extract_text_after_title(compact_block: str, title: str) -> str | None:
    if title == "Referencia":
        return extract_reference_details(compact_block)["reference"]

    if title == "Precio bruto unidad":
        return extract_input_value_after_title(compact_block, title, "precioBruto-")

    if title == "Tiempo de entrega":
        return extract_input_value_after_title(compact_block, title, "dias-")

    if title == "Descuento":
        return extract_input_value_after_title(compact_block, title, "descuentoAdi-")

    if title == "Calidad":
        selected_match = re.search(
            r'Calidad</span>.*?<span class="calidadSeleccionada">\s*([^<]+)\s*</span>',
            compact_block,
            re.IGNORECASE,
        )
        if selected_match:
            candidate = normalize_text(selected_match.group(1))
            return None if candidate.lower() == "seleccionar" else candidate or None
        return None

    if title == "Valor total":
        value_match = re.search(
            r'Valor total</span>.*?<span class="subtitulo txtCantidad">\s*([^<]+)\s*</span>',
            compact_block,
            re.IGNORECASE,
        )
        if value_match:
            candidate = normalize_text(value_match.group(1))
            return candidate or None
        return None

    pattern = re.compile(
        rf"{re.escape(title)}\s*</span>\s*</div>\s*<div[^>]*>\s*(.*?)\s*</div>",
        re.IGNORECASE,
    )
    match = pattern.search(compact_block)
    if not match:
        return None
    candidate = match.group(1)
    candidate = re.sub(r"<input[^>]*value=\"([^\"]*)\"[^>]*>", r"\1", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"<button[^>]*>\s*<span[^>]*>([^<]+)</span>.*?</button>", r"\1", candidate, flags=re.IGNORECASE)
    return normalize_text(candidate)


def extract_reference_details(compact_block: str) -> dict[str, str | None]:
    input_value = extract_input_value_after_title(compact_block, "Referencia")
    button_text = extract_button_text_after_title(compact_block, "Referencia")
    reference = input_value or button_text
    source = None
    if input_value:
        source = "input_value"
    elif button_text:
        source = "button_text"
    return {
        "reference": reference,
        "reference_input_value": input_value,
        "reference_button_text": button_text,
        "reference_source": source,
    }


def parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip()
    if not value.isdigit():
        return None
    return int(value)


def parse_part(block_html: str) -> ExtractedPart:
    compact = collapse_html(block_html)
    name = extract_part_name(compact) or "Unknown part"
    reference_details = extract_reference_details(compact)
    reference = reference_details["reference"]
    quantity = parse_int(extract_text_after_title(compact, "Cant."))
    unit_gross_price = extract_text_after_title(compact, "Precio bruto unidad")
    delivery_days = extract_text_after_title(compact, "Tiempo de entrega")
    discount = extract_text_after_title(compact, "Descuento")
    quality = extract_text_after_title(compact, "Calidad")
    total_value = extract_text_after_title(compact, "Valor total")
    validation_match = re.search(
        r"<span\b([^>]*)class=(?:\"|')[^\"']*sbc-success-text[^\"']*(?:\"|')([^>]*)>(.*?)</span>",
        compact,
        re.IGNORECASE,
    )
    reference_validation_text = normalize_text(validation_match.group(3)) if validation_match else None
    reference_validation_attrs = ""
    if validation_match:
        reference_validation_attrs = f"{validation_match.group(1)} {validation_match.group(2)}"
    reference_validation_visible = bool(reference_validation_text) and html_tag_is_visible(reference_validation_attrs)
    observation_match = re.search(
        r'class="txt-obervacion">\s*([^<]+)\s*</span>',
        compact,
        re.IGNORECASE,
    )
    observation_visible = normalize_text(observation_match.group(1)) if observation_match else None
    rejected_button_present = 'btn-rechazar' in compact.lower()

    missing = []
    if not reference:
        missing.append("reference")
    if quantity is None:
        missing.append("quantity")
    raw_status = "loaded" if not missing else f"partial_missing_{'_'.join(missing)}"

    return ExtractedPart(
        name=name,
        reference=reference,
        reference_input_value=reference_details["reference_input_value"],
        reference_button_text=reference_details["reference_button_text"],
        reference_source=reference_details["reference_source"],
        reference_validation_text=reference_validation_text,
        reference_validation_visible=reference_validation_visible,
        quantity=quantity,
        unit_gross_price=unit_gross_price,
        delivery_days=delivery_days,
        discount=discount,
        quality=quality,
        total_value=total_value,
        observation_visible=observation_visible,
        rejected_button_present=rejected_button_present,
        visible_dom_values={
            "reference": reference,
            "reference_input_value": reference_details["reference_input_value"],
            "reference_button_text": reference_details["reference_button_text"],
            "reference_validation": reference_validation_text,
            "reference_validation_visible": str(reference_validation_visible).lower(),
            "quantity": str(quantity) if quantity is not None else None,
            "unit_gross_price": unit_gross_price,
            "delivery_days": delivery_days,
            "discount": discount,
            "quality": quality,
            "total_value": total_value,
            "observation": observation_visible,
        },
        raw_status=raw_status,
    )


def parse_orbika_quote_html(html: str, quote_url: str, retries_used: int) -> ExtractedQuote:
    compact = collapse_html(html)
    warnings: list[str] = []
    aviso_id = extract_notice_id(compact)
    fecha_aviso = extract_notice_date(compact)
    taller_entrega = extract_delivery_workshop(compact)
    repuestos_cotizados, total_cotizacion = extract_footer_summary(compact)
    blocks = split_part_blocks(html)
    parts = [parse_part(block) for block in blocks]

    if not aviso_id:
        warnings.append("Notice ID was not found in the rendered page.")
    if not blocks:
        warnings.append("No quote-replacement blocks were found in the rendered page.")

    load_status = "loaded"
    if not aviso_id:
        load_status = "partial"
    elif not blocks and not repuestos_cotizados and not total_cotizacion:
        load_status = "partial"

    return ExtractedQuote(
        quote_url=quote_url,
        load_status=load_status,
        retries_used=retries_used,
        aviso_id=aviso_id,
        fecha_aviso=fecha_aviso,
        marca=extract_text_by_label(compact, TEXT_LABELS["marca"]),
        linea=extract_text_by_label(compact, TEXT_LABELS["linea"]),
        version=extract_text_by_label(compact, TEXT_LABELS["version"]),
        ano=extract_text_by_label(compact, TEXT_LABELS["ano"]),
        placa=extract_text_by_label(compact, TEXT_LABELS["placa"]),
        vin=extract_text_by_label(compact, TEXT_LABELS["vin"]),
        taller_entrega=taller_entrega,
        nombre_comercial=extract_text_by_label(compact, TEXT_LABELS["nombre_comercial"]),
        nit=extract_text_by_label(compact, TEXT_LABELS["nit"]),
        ciudad=extract_text_by_label(compact, TEXT_LABELS["ciudad"]),
        direccion=extract_text_by_label(compact, TEXT_LABELS["direccion"]),
        telefono=extract_text_by_label(compact, TEXT_LABELS["telefono"]),
        email=extract_text_by_label(compact, TEXT_LABELS["email"]),
        repuestos_count=len(parts),
        total_cotizacion=total_cotizacion,
        repuestos_cotizados=repuestos_cotizados,
        parts=parts,
        warnings=warnings,
    )


def get_playwright():
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit(
            "Missing Playwright dependency. Run with "
            "`uv run --with playwright python tools/orbika_quote_extractor.py ...` "
            "and install the browser with `uv run --with playwright python -m playwright install chromium`."
        ) from exc
    return sync_playwright, PlaywrightTimeoutError


def detect_browser_executable() -> str | None:
    configured = os.environ.get(PLAYWRIGHT_BROWSER_PATH_ENV, "").strip()
    if configured:
        return configured

    for candidate in [
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
        "chromium",
    ]:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def quote_page_ready(html: str) -> bool:
    compact = collapse_html(html).lower()
    quote_shell = quote_page_loaded(html)
    has_parts = "quote-replacement" in compact and 'class="tr-hd-lb' in compact
    has_footer_summary = "repuestos cotizados" in compact or "total cotización" in compact
    return quote_shell and (has_parts or has_footer_summary)


def quote_page_loaded(html: str) -> bool:
    compact = collapse_html(html).lower()
    return "manual-purchase" in compact and (
        'class="num-aviso"' in compact
        or "fecha del aviso" in compact
        or "marca:" in compact
        or "taller de entrega" in compact
    )


def quote_page_empty(html: str) -> bool:
    compact = collapse_html(html).lower()
    if not quote_page_loaded(html):
        return False
    has_notice_value = extract_notice_id(compact) is not None
    has_footer_summary = "repuestos cotizados" in compact or "total cotización" in compact
    return (
        not has_notice_value
        and has_footer_summary
        and "quote-replacement" not in compact
    )


def quote_read_flag_active(page: Any, html: str) -> bool:
    if is_interstitial_page(page, html):
        return False
    return quote_page_ready(html) or (quote_page_loaded(html) and not quote_page_empty(html))


def has_access_denied_marketplace_modal(html: str) -> bool:
    compact = collapse_html(html).lower()
    return (
        "actualmente no tienes permisos de acceso" in compact
        or "contacta al administrador para solicitar el ingreso" in compact
    )


def is_interstitial_page(page: Any, html: str) -> bool:
    compact = collapse_html(html).lower()
    page_url = page.url.lower()
    return (
        "seleccionar organización y rol" in compact
        or "select organization and role" in compact
        or has_access_denied_marketplace_modal(html)
        or "/web/guest/marketplace" in page_url
        or "/web/guest/notices/management" in page_url
        or ("/web/guest/login" in page_url and not quote_page_loaded(html))
    )


def is_signed_in_marketplace_shell(page: Any, html: str) -> bool:
    compact = collapse_html(html).lower()
    page_url = page.url.lower()
    return (
        "/web/guest/marketplace" in page_url
        and (
            "salir" in compact
            or "issignedin: function() { return true; }" in compact
            or "signed-in" in compact
        )
    )


def is_signed_out_shell(page: Any, html: str, allow_access_denied_modal: bool = False) -> bool:
    compact = collapse_html(html).lower()
    if has_access_denied_marketplace_modal(html) and not allow_access_denied_modal:
        return False
    return (
        (
            "signed-out" in compact
            or "issignedin: function() { return false; }" in compact
            or "acceder" in compact
        )
        and (
            bool(page.locator("#sign-in").count())
            or bool(page.locator("a.ingresar").count())
            or bool(page.locator("a:has-text('Acceder')").count())
        )
    )


def build_login_url_from_quote(quote_url: str) -> str:
    parts = urlsplit(quote_url)
    return urlunsplit((parts.scheme, parts.netloc, "/web/guest/login", "", ""))


def recover_quote_after_interstitial(
    page: Any,
    quote_url: str,
    timeout_ms: int,
    recovery_attempts: int,
    base_wait_ms: int,
    debug: DebugRecorder | None = None,
) -> tuple[str, bool]:
    html = page.content()
    for recovery_index in range(recovery_attempts):
        if debug:
            debug.log(
                "recover_attempt_start",
                recovery_index=recovery_index,
                current_url=mask_url(page.url),
                target_quote_url=mask_url(quote_url),
                recovery_attempts=recovery_attempts,
                base_wait_ms=base_wait_ms,
            )
        page.goto(quote_url, wait_until="domcontentloaded")
        page.wait_for_timeout(base_wait_ms + recovery_index * 1000)
        html = page.content()
        if debug:
            debug.log(
                "recover_after_goto",
                recovery_index=recovery_index,
                current_url=mask_url(page.url),
                quote_ready=quote_page_ready(html),
                quote_loaded=quote_page_loaded(html),
                quote_empty=quote_page_empty(html),
                interstitial=is_interstitial_page(page, html),
                signed_in_marketplace=is_signed_in_marketplace_shell(page, html),
            )
        if quote_read_flag_active(page, html):
            return html, True
        if is_interstitial_page(page, html):
            if debug:
                debug.snapshot(
                    f"recover-{recovery_index}-interstitial-before-reload",
                    html,
                    current_url=page.url,
                )
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(base_wait_ms + recovery_index * 1000)
            html = page.content()
            if debug:
                debug.log(
                    "recover_after_reload",
                    recovery_index=recovery_index,
                    current_url=mask_url(page.url),
                    quote_ready=quote_page_ready(html),
                    quote_loaded=quote_page_loaded(html),
                    quote_empty=quote_page_empty(html),
                    interstitial=is_interstitial_page(page, html),
                    signed_in_marketplace=is_signed_in_marketplace_shell(page, html),
                )
            if quote_read_flag_active(page, html):
                return html, True
    return html, False


def wait_for_login_form(page: Any, timeout_ms: int) -> bool:
    selectors = [
        "input[name*='_username']",
        "input[name*='_password']",
        "input.Rectangle-usuario",
        "input.Rectangle-contrasena",
        "input[type='password']",
    ]
    for selector in selectors:
        try:
            page.locator(selector).first.wait_for(timeout=timeout_ms)
            return True
        except Exception:
            continue
    return False


def ensure_login_if_needed(
    page: Any,
    quote_url: str,
    username: str | None,
    password: str | None,
    allow_marketplace_shell_login: bool = True,
    debug: DebugRecorder | None = None,
) -> bool:
    current_html = page.content()
    if is_signed_in_marketplace_shell(page, current_html):
        if debug:
            debug.log(
                "login_skipped_signed_in_marketplace",
                current_url=mask_url(page.url),
                allow_marketplace_shell_login=allow_marketplace_shell_login,
            )
        return False
    signed_out_shell = is_signed_out_shell(
        page,
        current_html,
        allow_access_denied_modal=allow_marketplace_shell_login,
    )
    login_form_present = (
        bool(page.locator("input[name*='_username']").count())
        or bool(page.locator("input[name*='_password']").count())
        or bool(page.locator("input.Rectangle-usuario").count())
        or bool(page.locator("input.Rectangle-contrasena").count())
        or "/web/guest/login" in page.url.lower()
    )
    login_needed = signed_out_shell or login_form_present
    if debug:
        debug.log(
            "login_check",
            current_url=mask_url(page.url),
            signed_out_shell=signed_out_shell,
            login_form_present=login_form_present,
            login_needed=login_needed,
            allow_marketplace_shell_login=allow_marketplace_shell_login,
            interstitial=is_interstitial_page(page, current_html),
            access_denied_modal=has_access_denied_marketplace_modal(current_html),
        )
    if not login_needed:
        return False
    if not username or not password:
        raise SystemExit(
            f"Orbika login is required for {mask_url(quote_url)}, but {ORBika_USERNAME_ENV}/{ORBika_PASSWORD_ENV} are not set."
        )

    if signed_out_shell:
        sign_in_selectors = [
            "#sign-in",
            "a.ingresar",
            "a:has-text('Acceder')",
            "text=Acceder",
        ]
        clicked_sign_in = False
        for selector in sign_in_selectors:
            locator = page.locator(selector).first
            if not locator.count():
                continue
            try:
                locator.click(force=True)
                if debug:
                    debug.log(
                        "sign_in_clicked",
                        selector=selector,
                        current_url=mask_url(page.url),
                    )
                clicked_sign_in = True
                break
            except Exception as exc:
                if debug:
                    debug.log(
                        "sign_in_click_failed",
                        selector=selector,
                        current_url=mask_url(page.url),
                        error=str(exc),
                    )
                continue
        if not clicked_sign_in:
            login_url = build_login_url_from_quote(quote_url)
            if debug:
                debug.log(
                    "sign_in_fallback_goto_login_url",
                    login_url=mask_url(login_url),
                    current_url=mask_url(page.url),
                )
            page.goto(login_url, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        if not wait_for_login_form(page, 8000):
            login_url = build_login_url_from_quote(quote_url)
            if debug:
                debug.log(
                    "login_form_missing_retry_goto_login_url",
                    login_url=mask_url(login_url),
                    current_url=mask_url(page.url),
                )
            page.goto(login_url, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            wait_for_login_form(page, 8000)

    username_locators = [
        "input[name*='_username']",
        "input.Rectangle-usuario",
        "input[name='username']",
        "input[name='user']",
        "input[name='email']",
        "input[id*='user' i]",
        "input[id*='login' i]",
        "input[type='email']",
        "input[type='text']",
    ]
    password_locators = [
        "input[name*='_password']",
        "input.Rectangle-contrasena",
        "input[type='password']",
        "input[name='password']",
        "input[id*='pass' i]",
    ]
    terms_locators = [
        "input[name*='_terminos']",
        "input[type='checkbox'][required]",
    ]
    submit_locators = [
        "input[type='submit'][value='Ingresar']",
        "button[type='submit']",
        "button:has-text('Ingresar')",
        "button:has-text('Login')",
        "button:has-text('Entrar')",
        "input[type='submit']",
    ]

    username_filled = False
    password_filled = False
    password_locator = None

    for selector in username_locators:
        locator = page.locator(selector).first
        if locator.count():
            try:
                locator.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass
            locator.fill(username)
            username_filled = True
            break
    for selector in password_locators:
        locator = page.locator(selector).first
        if locator.count():
            password_locator = locator
            try:
                locator.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass
            locator.fill(password)
            password_filled = True
            break

    if not username_filled:
        visible_text_like = page.locator(
            "input:not([type='hidden']):not([type='password']):not([disabled])"
        )
        count = visible_text_like.count()
        for index in range(count):
            locator = visible_text_like.nth(index)
            try:
                locator.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass
            locator.fill(username)
            username_filled = True
            break

    if not password_filled:
        visible_password_like = page.locator("input[type='password']:not([disabled])")
        count = visible_password_like.count()
        for index in range(count):
            locator = visible_password_like.nth(index)
            try:
                locator.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass
            password_locator = locator
            locator.fill(password)
            password_filled = True
            break

    if not username_filled or not password_filled:
        snapshot_dir = DEFAULT_HTML_SNAPSHOT_DIR
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_file = snapshot_dir / "login-page.html"
        snapshot_file.write_text(page.content(), encoding="utf-8")
        if debug:
            debug.snapshot("login-fields-not-found", page.content(), current_url=page.url)
        raise SystemExit(
            "Orbika login page was detected for "
            f"{mask_url(quote_url)}, but the visible username/password fields were not found. "
            f"A login snapshot was saved to {snapshot_file}."
        )

    for selector in terms_locators:
        locator = page.locator(selector).first
        if locator.count():
            if not locator.is_checked():
                locator.check(force=True)
            break

    clicked_submit = False
    for selector in submit_locators:
        locator = page.locator(selector).first
        if locator.count():
            locator.click(force=True)
            if debug:
                debug.log(
                    "login_submit_clicked",
                    selector=selector,
                    current_url=mask_url(page.url),
                )
            clicked_submit = True
            break

    if not clicked_submit and password_locator is not None:
        if debug:
            debug.log(
                "login_submit_via_enter",
                current_url=mask_url(page.url),
            )
        password_locator.press("Enter")
    return True


def fetch_quote_html(
    quote_url: str,
    storage_state_path: Path,
    headed: bool,
    timeout_ms: int,
    max_retries: int,
    snapshot_dir: Path | None,
    allow_login_fallback: bool = False,
) -> tuple[str, int]:
    sync_playwright, PlaywrightTimeoutError = get_playwright()
    username = os.environ.get(ORBika_USERNAME_ENV)
    password = os.environ.get(ORBika_PASSWORD_ENV)
    executable_path = detect_browser_executable()
    debug = build_debug_recorder()
    debug.log(
        "fetch_quote_html_start",
        quote_url=mask_url(quote_url),
        storage_state_path=str(storage_state_path),
        headed=headed,
        timeout_ms=timeout_ms,
        max_retries=max_retries,
        allow_login_fallback=allow_login_fallback,
        executable_path=executable_path,
    )

    with sync_playwright() as playwright:
        launch_kwargs: dict[str, Any] = {"headless": not headed}
        if executable_path:
            launch_kwargs["executable_path"] = executable_path
        browser = playwright.chromium.launch(**launch_kwargs)
        context_args: dict[str, Any] = {}
        if storage_state_path.exists():
            context_args["storage_state"] = str(storage_state_path)
        context = browser.new_context(**context_args)
        page = context.new_page()
        page.set_default_timeout(timeout_ms)

        retries_used = 0
        html = ""
        login_attempted_during_fetch = False
        for attempt in range(max_retries + 1):
            retries_used = attempt
            debug.log(
                "attempt_start",
                attempt=attempt,
                current_url=mask_url(page.url),
                quote_url=mask_url(quote_url),
                login_attempted_during_fetch=login_attempted_during_fetch,
            )
            page.goto(quote_url, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            html = page.content()
            debug.log(
                "after_initial_goto",
                attempt=attempt,
                current_url=mask_url(page.url),
                quote_ready=quote_page_ready(html),
                quote_loaded=quote_page_loaded(html),
                quote_empty=quote_page_empty(html),
                interstitial=is_interstitial_page(page, html),
                signed_in_marketplace=is_signed_in_marketplace_shell(page, html),
                access_denied_modal=has_access_denied_marketplace_modal(html),
            )
            if is_interstitial_page(page, html):
                debug.snapshot(f"attempt-{attempt}-initial-interstitial", html, current_url=page.url)
                html, quote_read_confirmed = recover_quote_after_interstitial(
                    page=page,
                    quote_url=quote_url,
                    timeout_ms=timeout_ms,
                    recovery_attempts=max(3, 2 + attempt),
                    base_wait_ms=2000 + attempt * 1000,
                    debug=debug,
                )
                debug.log(
                    "post_initial_interstitial_recovery_result",
                    attempt=attempt,
                    current_url=mask_url(page.url),
                    quote_read_confirmed=quote_read_confirmed,
                    quote_ready=quote_page_ready(html),
                    quote_loaded=quote_page_loaded(html),
                    quote_empty=quote_page_empty(html),
                    interstitial=is_interstitial_page(page, html),
                )
                if quote_read_confirmed:
                    break
            if allow_login_fallback and ensure_login_if_needed(
                page,
                quote_url,
                username,
                password,
                allow_marketplace_shell_login=not login_attempted_during_fetch,
                debug=debug,
            ):
                login_attempted_during_fetch = True
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(2000)
                html, quote_read_confirmed = recover_quote_after_interstitial(
                    page=page,
                    quote_url=quote_url,
                    timeout_ms=timeout_ms,
                    recovery_attempts=max(4, 3 + attempt * 2),
                    base_wait_ms=3000 + attempt * 1000,
                    debug=debug,
                )
                debug.log(
                    "post_login_recovery_result",
                    attempt=attempt,
                    current_url=mask_url(page.url),
                    quote_read_confirmed=quote_read_confirmed,
                    quote_ready=quote_page_ready(html),
                    quote_loaded=quote_page_loaded(html),
                    quote_empty=quote_page_empty(html),
                    interstitial=is_interstitial_page(page, html),
                )
                if quote_read_confirmed:
                    break
                page.goto(quote_url, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)

            for selector in QUOTE_SHELL_SELECTORS:
                try:
                    page.locator(selector).first.wait_for(timeout=timeout_ms // 2)
                except PlaywrightTimeoutError:
                    continue

            html = page.content()
            quote_read_confirmed = quote_read_flag_active(page, html)
            debug.log(
                "after_quote_shell_wait",
                attempt=attempt,
                current_url=mask_url(page.url),
                quote_read_confirmed=quote_read_confirmed,
                quote_ready=quote_page_ready(html),
                quote_loaded=quote_page_loaded(html),
                quote_empty=quote_page_empty(html),
                interstitial=is_interstitial_page(page, html),
            )
            if not quote_read_confirmed and is_interstitial_page(page, html):
                debug.snapshot(f"attempt-{attempt}-shell-interstitial", html, current_url=page.url)
                html, quote_read_confirmed = recover_quote_after_interstitial(
                    page=page,
                    quote_url=quote_url,
                    timeout_ms=timeout_ms,
                    recovery_attempts=2 + attempt,
                    base_wait_ms=2500 + attempt * 1000,
                    debug=debug,
                )

            for selector in QUOTE_READY_SELECTORS:
                try:
                    page.locator(selector).first.wait_for(timeout=timeout_ms // 3)
                except PlaywrightTimeoutError:
                    continue

            html = page.content()
            quote_read_confirmed = quote_read_flag_active(page, html)
            debug.log(
                "attempt_result",
                attempt=attempt,
                current_url=mask_url(page.url),
                quote_read_confirmed=quote_read_confirmed,
                quote_ready=quote_page_ready(html),
                quote_loaded=quote_page_loaded(html),
                quote_empty=quote_page_empty(html),
                interstitial=is_interstitial_page(page, html),
                signed_in_marketplace=is_signed_in_marketplace_shell(page, html),
                access_denied_modal=has_access_denied_marketplace_modal(html),
            )
            if quote_page_ready(html):
                break
            if quote_read_confirmed:
                break

            if attempt < max_retries:
                debug.snapshot(f"attempt-{attempt}-before-retry", html, current_url=page.url)
                page.goto(quote_url, wait_until="domcontentloaded")
                page.wait_for_timeout(3000 + attempt * 1500)
                html = page.content()
                quote_read_confirmed = quote_read_flag_active(page, html)
                debug.log(
                    "retry_after_goto",
                    attempt=attempt,
                    current_url=mask_url(page.url),
                    quote_read_confirmed=quote_read_confirmed,
                    quote_ready=quote_page_ready(html),
                    quote_loaded=quote_page_loaded(html),
                    quote_empty=quote_page_empty(html),
                    interstitial=is_interstitial_page(page, html),
                )
                if not quote_read_confirmed and (quote_page_empty(html) or is_interstitial_page(page, html)):
                    debug.snapshot(f"attempt-{attempt}-retry-pre-reload", html, current_url=page.url)
                    page.reload(wait_until="domcontentloaded")
                    page.wait_for_timeout(3000 + attempt * 1500)
                    html = page.content()
                    quote_read_confirmed = quote_read_flag_active(page, html)
                    debug.log(
                        "retry_after_reload",
                        attempt=attempt,
                        current_url=mask_url(page.url),
                        quote_read_confirmed=quote_read_confirmed,
                        quote_ready=quote_page_ready(html),
                        quote_loaded=quote_page_loaded(html),
                        quote_empty=quote_page_empty(html),
                        interstitial=is_interstitial_page(page, html),
                    )
                    if not quote_read_confirmed:
                        html, quote_read_confirmed = recover_quote_after_interstitial(
                            page=page,
                            quote_url=quote_url,
                            timeout_ms=timeout_ms,
                            recovery_attempts=2 + attempt,
                            base_wait_ms=3000 + attempt * 1500,
                            debug=debug,
                        )
                    if quote_read_confirmed:
                        break

        storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(storage_state_path))
        debug.log(
            "fetch_quote_html_end",
            current_url=mask_url(page.url),
            retries_used=retries_used,
            quote_ready=quote_page_ready(html),
            quote_loaded=quote_page_loaded(html),
            quote_empty=quote_page_empty(html),
            interstitial=is_interstitial_page(page, html),
        )
        browser.close()

    if snapshot_dir:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_file = snapshot_dir / f"quote-{retries_used}.html"
        snapshot_file.write_text(html, encoding="utf-8")
        debug.log("final_snapshot_saved", path=str(snapshot_file))

    return html, retries_used


def write_json(path: Path, records: list[ExtractedQuote]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "records": [asdict(record) for record in records],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_csv(path: Path, records: list[ExtractedQuote]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "quote_url",
                "load_status",
                "retries_used",
                "aviso_id",
                "fecha_aviso",
                "marca",
                "linea",
                "version",
                "ano",
                "placa",
                "vin",
                "taller_entrega",
                "nombre_comercial",
                "nit",
                "ciudad",
                "direccion",
                "telefono",
                "email",
                "repuestos_count",
                "repuestos_cotizados",
                "total_cotizacion",
                "warnings",
            ],
        )
        writer.writeheader()
        for record in records:
            row = asdict(record)
            row.pop("parts", None)
            row["warnings"] = " | ".join(record.warnings)
            writer.writerow(row)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only Orbika extractor for quote URLs from Gmail phase 1."
    )
    parser.add_argument("--quote-url", action="append", default=[], help="Single quote URL to process.")
    parser.add_argument(
        "--input-json",
        type=Path,
        default=None,
        help="Optional phase 1 JSON output to load extracted quote URLs from.",
    )
    parser.add_argument(
        "--storage-state",
        type=Path,
        default=DEFAULT_STORAGE_STATE,
        help=f"Playwright storage state path outside the repo. Default: {DEFAULT_STORAGE_STATE}",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "orbika_quotes.json",
        help="Local JSON output path. Default is gitignored.",
    )
    parser.add_argument("--csv-output", type=Path, default=None, help="Optional CSV output path.")
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=DEFAULT_HTML_SNAPSHOT_DIR,
        help="Optional snapshot directory for rendered HTML debugging.",
    )
    parser.add_argument("--timeout-ms", type=int, default=15000)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--headed", action="store_true", help="Run browser in headed mode.")
    parser.add_argument(
        "--allow-login-fallback",
        action="store_true",
        help="Allow Orbika username/password login only as a fallback after quote URL reload recovery fails.",
    )
    return parser.parse_args(argv)


def collect_quote_urls(args: argparse.Namespace) -> list[str]:
    urls = list(args.quote_url)
    if args.input_json:
        if not args.input_json.exists():
            raise SystemExit(f"Phase 1 JSON input not found: {args.input_json}")
        urls.extend(quotes_from_phase1_json(args.input_json))
    unique_urls = []
    seen = set()
    for url in urls:
        clean = str(url).strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        unique_urls.append(clean)
    if not unique_urls:
        raise SystemExit("Provide at least one --quote-url or --input-json from phase 1 output.")
    return unique_urls


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    repo_root = Path.cwd()
    reject_repo_secret_path(args.storage_state.expanduser(), repo_root, "Playwright storage state")

    records: list[ExtractedQuote] = []
    for quote_url in collect_quote_urls(args):
        html, retries_used = fetch_quote_html(
            quote_url=quote_url,
            storage_state_path=args.storage_state.expanduser(),
            headed=args.headed,
            timeout_ms=args.timeout_ms,
            max_retries=args.max_retries,
            snapshot_dir=args.snapshot_dir,
            allow_login_fallback=args.allow_login_fallback,
        )
        record = parse_orbika_quote_html(html, quote_url, retries_used)
        if not quote_page_ready(html):
            record.load_status = "failed_after_retries"
            if "Rendered quote page was still incomplete after retries." not in record.warnings:
                record.warnings.append("Rendered quote page was still incomplete after retries.")
        records.append(record)

    write_json(args.json_output, records)
    if args.csv_output:
        write_csv(args.csv_output, records)

    loaded = sum(1 for record in records if record.load_status == "loaded")
    print(
        f"Processed {len(records)} Orbika quote(s); "
        f"{loaded} loaded fully. Output: {args.json_output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
