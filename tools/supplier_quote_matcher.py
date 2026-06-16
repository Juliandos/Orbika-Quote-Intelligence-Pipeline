#!/usr/bin/env python3
"""Local supplier matching for extracted Orbika quotes."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


DEFAULT_PROVIDERS_ROOT = Path("supplier_catalog/providers")
DEFAULT_QUOTES_DIR = Path("local/orbika_incremental/quotes")
DEFAULT_DAILY_REPORT_DIR = Path("local/orbika_incremental/daily")
_SKIP = object()
MAX_STORED_MATCHES_PER_PART = 3

STOPWORDS = {
    "a",
    "al",
    "con",
    "de",
    "del",
    "el",
    "en",
    "la",
    "las",
    "los",
    "para",
    "por",
    "sin",
    "un",
    "una",
    "y",
}

GENERIC_VEHICLE_TOKENS = {
    "aa",
    "ab",
    "abs",
    "año",
    "ano",
    "at",
    "ct",
    "fl",
    "mt",
    "model",
    "modelo",
    "modelos",
    "sport",
    "tp",
}

GENERIC_PART_DESCRIPTOR_TOKENS = {
    "central",
    "delantera",
    "delantero",
    "derecha",
    "derecho",
    "exterior",
    "frontal",
    "inferior",
    "inner",
    "inside",
    "interior",
    "izquierda",
    "izquierdo",
    "lado",
    "left",
    "rear",
    "right",
    "superior",
    "trasera",
    "trasero",
}

KNOWN_VEHICLE_BRANDS = frozenset(
    {
        "audi",
        "bmw",
        "byd",
        "changan",
        "chery",
        "chevrolet",
        "citroen",
        "cupra",
        "dfsk",
        "dodge",
        "fiat",
        "ford",
        "foton",
        "geely",
        "greatwall",
        "great",
        "gwm",
        "haval",
        "hino",
        "honda",
        "hyundai",
        "isuzu",
        "iveco",
        "jac",
        "jeep",
        "jetour",
        "jinbei",
        "kia",
        "lada",
        "mazda",
        "mercedes",
        "mg",
        "mini",
        "mitsubishi",
        "nissan",
        "peugeot",
        "porsche",
        "ram",
        "renault",
        "seat",
        "skoda",
        "subaru",
        "suzuki",
        "tesla",
        "toyota",
        "volkswagen",
        "volvo",
    }
)

TAXONOMY_KEYWORDS = {
    "accessories_misc": [
        "accesorio",
        "accesorios",
        "antena",
        "broche",
        "broches",
        "emblema",
        "insonorizante",
        "kit",
        "sello",
        "tapete",
    ],
    "belts_tensioners": [
        "correa",
        "correas",
        "kit distribucion",
        "polea",
        "poleas",
        "reparticion",
        "tensor",
        "tensores",
    ],
    "body_panels": [
        "aleta",
        "bocel",
        "bomper",
        "bumber",
        "capo",
        "compuerta",
        "guardafango",
        "guia lateral",
        "parachoque",
        "panel",
        "puerta",
        "spoiler",
    ],
    "brake_fluids": [
        "brake fluid",
        "liquido de frenos",
    ],
    "brake_system": [
        "abs",
        "balata",
        "balatas",
        "bomba de freno",
        "campana",
        "disco de freno",
        "discos de freno",
        "freno",
        "frenos",
        "mordaza",
        "pastilla",
        "pastillas",
        "sensor abs",
        "zapatas",
    ],
    "cooling": [
        "bomba de agua",
        "condensador",
        "coolant",
        "electroventilador",
        "manguera",
        "mangueras",
        "radiador",
        "refrigeracion",
        "refrigerante",
        "refrigerantes",
        "termostato",
    ],
    "driveline": [
        "cardan",
        "cruceta",
        "crucetas",
        "diferencial",
        "homocinetica",
        "semieje",
        "transmision",
    ],
    "engine_components": [
        "bomba aceite",
        "culata",
        "empaque",
        "motor",
        "piston",
        "pistones",
        "valvula",
        "valvulas",
    ],
    "filters": [
        "filtro",
        "filtros",
        "filtracion",
    ],
    "fuel_delivery": [
        "bomba de combustible",
        "bomba gasolina",
        "inyector",
        "inyectores",
    ],
    "ignition_electrical": [
        "alternador",
        "arranque",
        "bateria",
        "bobina",
        "bomba electrica",
        "bujia",
        "bujias",
        "cable electrico",
        "cables electricos",
        "electrico",
        "electrica",
        "electricas",
        "electrico",
        "sensor",
        "switch",
        "terminal electrico",
    ],
    "lighting_headlamps": [
        "bombillo",
        "bombillos",
        "exploradora",
        "faro",
        "farola",
        "farolas",
        "iluminacion",
        "luz",
        "luces",
        "stop",
    ],
    "lubricants_fluids": [
        "aceite",
        "aceites",
        "aditivo",
        "aditivos",
        "grasa",
        "grasas",
        "lubricacion",
        "lubricante",
        "lubricantes",
        "quimico",
        "quimicos",
    ],
    "suspension_steering": [
        "amortiguador",
        "amortiguadores",
        "axial",
        "barra central",
        "brazo compensador",
        "buje",
        "bujes",
        "caja de direccion",
        "cajas de direccion",
        "direccion",
        "guaya direccion",
        "lagrima",
        "lagrimas",
        "rodamiento",
        "rodamientos",
        "rotula",
        "rotulas",
        "semieje",
        "soporte amortiguador",
        "soportes de amortiguador",
        "suspension",
        "terminal",
        "terminales",
        "tijera",
        "tijeras",
    ],
    "wipers_visibility": [
        "limpiaparabrisas",
        "limpiavidrio",
        "plumilla",
        "plumillas",
        "visibilidad",
    ],
}


def _compact_scalar_for_storage(value: Any) -> Any:
    if value is None:
        return _SKIP
    if isinstance(value, str) and not value.strip():
        return _SKIP
    return value


def _compact_value_for_storage(value: Any) -> Any:
    if isinstance(value, dict):
        compacted: dict[str, Any] = {}
        for key, item in value.items():
            compact_item = _compact_value_for_storage(item)
            if compact_item is _SKIP:
                continue
            compacted[key] = compact_item
        return compacted or _SKIP
    if isinstance(value, list):
        compacted_list = [
            compact_item
            for item in value
            if (compact_item := _compact_value_for_storage(item)) is not _SKIP
        ]
        return compacted_list or _SKIP
    return _compact_scalar_for_storage(value)


def compact_provider_spec_for_storage(spec: dict[str, Any]) -> dict[str, Any]:
    compacted = _compact_value_for_storage(
        {
            "provider_id": spec.get("provider_id"),
            "display_name": spec.get("display_name"),
            "snapshot_date": spec.get("snapshot_date"),
        }
    )
    return compacted if isinstance(compacted, dict) else {}


def compact_match_entry_for_storage(entry: dict[str, Any]) -> dict[str, Any]:
    compacted = _compact_value_for_storage(
        {
            "provider_id": entry.get("provider_id"),
            "provider_name": entry.get("provider_name"),
            "score_percent": entry.get("score_percent"),
            "match_type": entry.get("match_type"),
            "detail_url": entry.get("detail_url"),
            "product_name": entry.get("product_name"),
            "reference": entry.get("reference"),
            "sku": entry.get("sku"),
            "brand": entry.get("brand"),
            "category_name": entry.get("category_name"),
            "subcategory_name": entry.get("subcategory_name"),
        }
    )
    return compacted if isinstance(compacted, dict) else {}


def compact_supplier_summary_for_storage(summary: dict[str, Any]) -> dict[str, Any]:
    compacted = _compact_value_for_storage(
        {
            "parts_total": summary.get("parts_total"),
            "parts_with_matches": summary.get("parts_with_matches"),
            "exact_reference_matches": summary.get("exact_reference_matches"),
            "provider_hits": summary.get("provider_hits"),
        }
    )
    return compacted if isinstance(compacted, dict) else {}


def compact_supplier_match_part_for_storage(part: dict[str, Any]) -> dict[str, Any]:
    compacted = _compact_value_for_storage(
        {
            "part_name": part.get("part_name"),
            "requested_reference": part.get("requested_reference"),
            "quantity": part.get("quantity"),
            "best_score_percent": part.get("best_score_percent"),
            "best_match_type": part.get("best_match_type"),
            "best_provider_id": part.get("best_provider_id"),
            "matches": [
                compact_match_entry_for_storage(match)
                for match in part.get("matches", [])[:MAX_STORED_MATCHES_PER_PART]
            ],
        }
    )
    return compacted if isinstance(compacted, dict) else {}


def compact_supplier_matching_for_storage(report: dict[str, Any]) -> dict[str, Any]:
    compacted = _compact_value_for_storage(
        {
            "generated_at": report.get("generated_at"),
            "summary": compact_supplier_summary_for_storage(report.get("summary", {})),
            "provider_specs": [
                compact_provider_spec_for_storage(spec)
                for spec in report.get("provider_specs", [])
            ],
            "parts": [
                compact_supplier_match_part_for_storage(part)
                for part in report.get("parts", [])
            ],
        }
    )
    return compacted if isinstance(compacted, dict) else {}


def compact_orbika_part_for_storage(part: dict[str, Any]) -> dict[str, Any]:
    compacted = _compact_value_for_storage(
        {
            "name": part.get("name"),
            "reference": part.get("reference"),
            "quantity": part.get("quantity"),
            "unit_gross_price": part.get("unit_gross_price"),
            "delivery_days": part.get("delivery_days"),
            "discount": part.get("discount"),
            "quality": part.get("quality"),
            "total_value": part.get("total_value"),
            "reference_validation_text": part.get("reference_validation_text"),
            "raw_status": part.get("raw_status"),
        }
    )
    return compacted if isinstance(compacted, dict) else {}


def compact_orbika_for_storage(orbika: dict[str, Any]) -> dict[str, Any]:
    compacted = _compact_value_for_storage(
        {
            "load_status": orbika.get("load_status"),
            "retries_used": orbika.get("retries_used"),
            "aviso_id": orbika.get("aviso_id"),
            "fecha_aviso": orbika.get("fecha_aviso"),
            "marca": orbika.get("marca"),
            "linea": orbika.get("linea"),
            "version": orbika.get("version"),
            "ano": orbika.get("ano"),
            "placa": orbika.get("placa"),
            "vin": orbika.get("vin"),
            "taller_entrega": orbika.get("taller_entrega"),
            "nombre_comercial": orbika.get("nombre_comercial"),
            "nit": orbika.get("nit"),
            "ciudad": orbika.get("ciudad"),
            "direccion": orbika.get("direccion"),
            "telefono": orbika.get("telefono"),
            "email": orbika.get("email"),
            "repuestos_count": orbika.get("repuestos_count"),
            "total_cotizacion": orbika.get("total_cotizacion"),
            "repuestos_cotizados": orbika.get("repuestos_cotizados"),
            "parts": [
                compact_orbika_part_for_storage(part)
                for part in orbika.get("parts", [])
            ],
            "warnings": orbika.get("warnings"),
        }
    )
    return compacted if isinstance(compacted, dict) else {}


def compact_agentic_match_for_storage(entry: dict[str, Any]) -> dict[str, Any]:
    compacted = _compact_value_for_storage(
        {
            "rank": entry.get("rank"),
            "provider_id": entry.get("provider_id"),
            "provider_name": entry.get("provider_name"),
            "score_percent": entry.get("score_percent"),
            "match_type": entry.get("match_type"),
            "product_name": entry.get("product_name"),
            "detail_url": entry.get("detail_url"),
            "reference": entry.get("reference"),
            "brand": entry.get("brand"),
            "category_name": entry.get("category_name"),
            "agentic_comment": entry.get("agentic_comment"),
        }
    )
    return compacted if isinstance(compacted, dict) else {}


def compact_agentic_summary_for_storage(summary: dict[str, Any]) -> dict[str, Any]:
    compacted = _compact_value_for_storage(
        {
            "parts_reviewed": summary.get("parts_reviewed"),
            "parts_with_agentic_matches": summary.get("parts_with_agentic_matches"),
            "provider_hits": summary.get("provider_hits"),
        }
    )
    return compacted if isinstance(compacted, dict) else {}


def compact_agentic_part_for_storage(part: dict[str, Any]) -> dict[str, Any]:
    compacted = _compact_value_for_storage(
        {
            "part_name": part.get("part_name"),
            "requested_reference": part.get("requested_reference"),
            "top_provider_id": part.get("top_provider_id"),
            "top_score_percent": part.get("top_score_percent"),
            "selected_matches": [
                compact_agentic_match_for_storage(match)
                for match in part.get("selected_matches", [])
            ],
        }
    )
    return compacted if isinstance(compacted, dict) else {}


def compact_agentic_supplier_matching_for_storage(report: dict[str, Any]) -> dict[str, Any]:
    compacted = _compact_value_for_storage(
        {
            "generated_at": report.get("generated_at"),
            "review_mode": report.get("review_mode"),
            "summary": compact_agentic_summary_for_storage(report.get("summary", {})),
            "parts": [
                compact_agentic_part_for_storage(part)
                for part in report.get("parts", [])
            ],
        }
    )
    return compacted if isinstance(compacted, dict) else {}


def compact_source_for_storage(source: dict[str, Any]) -> dict[str, Any]:
    compacted = _compact_value_for_storage(
        {
            "message_id": source.get("message_id"),
            "received_at": source.get("received_at"),
            "subject": source.get("subject"),
        }
    )
    return compacted if isinstance(compacted, dict) else {}


def compact_quote_payload_for_storage(quote_payload: dict[str, Any]) -> dict[str, Any]:
    compacted = _compact_value_for_storage(
        {
            "generated_at": quote_payload.get("generated_at"),
            "quote_key": quote_payload.get("quote_key"),
            "source": compact_source_for_storage(quote_payload.get("source", {})),
            "quote_url_masked": quote_payload.get("quote_url_masked"),
            "orbika": compact_orbika_for_storage(quote_payload.get("orbika", {})),
            "supplier_matching": compact_supplier_matching_for_storage(
                quote_payload.get("supplier_matching", {})
            )
            if quote_payload.get("supplier_matching")
            else None,
            "agentic_supplier_matching": compact_agentic_supplier_matching_for_storage(
                quote_payload.get("agentic_supplier_matching", {})
            )
            if quote_payload.get("agentic_supplier_matching")
            else None,
        }
    )
    return compacted if isinstance(compacted, dict) else {}

PART_SIGNAL_PRIORITY = (
    "fuel_filter",
    "fuel_pump",
    "wiper_kit",
    "wiper",
    "spark_plug",
    "filter",
)

PART_SIGNAL_COMPATIBILITY = {
    "fuel_filter": {"fuel_filter"},
    "fuel_pump": {"fuel_pump"},
    "wiper_kit": {"wiper_kit"},
    "wiper": {"wiper", "wiper_kit"},
    "spark_plug": {"spark_plug"},
    "filter": {"filter", "fuel_filter"},
}

KIT_HINT_TOKENS = frozenset({"kit", "jgo", "jgox2", "jgx2", "juego", "par"})

COMMON_PROVIDER_NOTES = {
    "disfal": (
        "No hay referencias exactas publicas; Disfal parece relevante por familia o marca, "
        "pero requiere confirmacion manual."
    ),
    "impocali": (
        "No hay referencias exactas publicas; Impocali probablemente maneja esta familia, "
        "pero requiere confirmacion manual."
    ),
    "partcar": (
        "El catalogo usa un codigo interno del proveedor; se recomienda confirmar equivalencia "
        "antes de tomarlo como reemplazo exacto."
    ),
}


@dataclass
class ProviderItem:
    provider_id: str
    provider_name: str
    provider_type: str
    detail_url: str | None
    title: str
    category_name: str | None
    subcategory_name: str | None
    brand: str | None
    reference: str | None
    sku: str | None
    supplier_item_code: str | None
    taxonomy_labels: tuple[str, ...]
    searchable_tokens: frozenset[str]
    raw_match_type: str | None
    requires_manual_confirmation: bool
    notes: tuple[str, ...]


@dataclass
class CatalogIndex:
    items: list[ProviderItem]
    provider_specs: dict[str, dict[str, Any]]
    references: dict[str, set[int]]
    tokens: dict[str, set[int]]
    taxonomies: dict[str, set[int]]


@dataclass(frozen=True)
class VehicleProfile:
    brand_tokens: frozenset[str]
    line_tokens: frozenset[str]
    version_tokens: frozenset[str]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def strip_accents(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )


def normalize_text(value: str | None) -> str:
    text = strip_accents(value or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_reference(value: str | None) -> str | None:
    normalized = re.sub(r"[^A-Za-z0-9]+", "", (value or "").upper())
    return normalized or None


def token_set(*values: str | None) -> frozenset[str]:
    merged = " ".join(value or "" for value in values)
    tokens = []
    for token in normalize_text(merged).split():
        if token in STOPWORDS:
            continue
        if len(token) == 1:
            continue
        tokens.append(token)
    return frozenset(tokens)


def filtered_token_set(*values: str | None, ignored_tokens: set[str] | frozenset[str]) -> frozenset[str]:
    return frozenset(token for token in token_set(*values) if token not in ignored_tokens)


def part_query_tokens(part_name: str | None, reference: str | None) -> frozenset[str]:
    return filtered_token_set(
        part_name,
        reference,
        ignored_tokens=GENERIC_PART_DESCRIPTOR_TOKENS,
    )


def text_contains_pattern(
    normalized_text: str,
    normalized_tokens: frozenset[str],
    pattern: str,
) -> bool:
    normalized_pattern = normalize_text(pattern)
    if not normalized_pattern:
        return False
    if " " in normalized_pattern:
        return f" {normalized_pattern} " in f" {normalized_text} "
    return normalized_pattern in normalized_tokens


def infer_primary_part_signal(*values: str | None) -> str | None:
    normalized_text = normalize_text(" ".join(value or "" for value in values))
    normalized_tokens = token_set(*values)

    has_filter = "filtro" in normalized_tokens or "filtros" in normalized_tokens
    has_fuel = "combustible" in normalized_tokens
    has_wiper = bool(
        {"plumilla", "plumillas", "limpiavidrio", "limpiaparabrisas"} & normalized_tokens
    )
    has_kit_hint = bool(KIT_HINT_TOKENS & normalized_tokens)

    inferred: set[str] = set()
    if has_filter and has_fuel:
        inferred.add("fuel_filter")
    if text_contains_pattern(normalized_text, normalized_tokens, "bomba de combustible") or (
        "bomba" in normalized_tokens and has_fuel
    ):
        inferred.add("fuel_pump")
    if has_wiper and ("kit" in normalized_tokens or has_kit_hint):
        inferred.add("wiper_kit")
    if has_wiper:
        inferred.add("wiper")
    if "bujia" in normalized_tokens or "bujias" in normalized_tokens:
        inferred.add("spark_plug")
    if has_filter or "filtracion" in normalized_tokens:
        inferred.add("filter")

    for signal in PART_SIGNAL_PRIORITY:
        if signal in inferred:
            return signal
    return None


def part_signal_points(query_signal: str | None, item_signal: str | None) -> int:
    if not query_signal or not item_signal:
        return 0
    if item_signal not in PART_SIGNAL_COMPATIBILITY.get(query_signal, {query_signal}):
        return 0
    if query_signal == item_signal:
        if query_signal in {"fuel_filter", "fuel_pump", "wiper_kit", "spark_plug"}:
            return 28
        return 24
    return 20


def vehicle_profile_from_quote_context(quote_context: dict[str, Any]) -> VehicleProfile:
    brand_tokens = token_set(quote_context.get("marca"))
    line_tokens = filtered_token_set(
        quote_context.get("linea"),
        ignored_tokens=GENERIC_VEHICLE_TOKENS | set(brand_tokens),
    )
    version_tokens = filtered_token_set(
        quote_context.get("version"),
        ignored_tokens=GENERIC_VEHICLE_TOKENS | set(brand_tokens) | set(line_tokens),
    )
    return VehicleProfile(
        brand_tokens=brand_tokens,
        line_tokens=line_tokens,
        version_tokens=version_tokens,
    )


def item_brand_tokens(item: ProviderItem) -> frozenset[str]:
    explicit_brand_tokens = token_set(item.brand)
    if explicit_brand_tokens:
        vehicle_brand_tokens = frozenset(
            token for token in explicit_brand_tokens if token in KNOWN_VEHICLE_BRANDS
        )
        if vehicle_brand_tokens:
            return vehicle_brand_tokens
    return frozenset(token for token in item.searchable_tokens if token in KNOWN_VEHICLE_BRANDS)


def item_has_vehicle_scope(item: ProviderItem) -> bool:
    normalized_title = normalize_text(item.title)
    if item_brand_tokens(item):
        return True
    return " modelo " in f" {normalized_title} " or " modelos " in f" {normalized_title} "


def vehicle_compatibility(
    quote_vehicle: VehicleProfile,
    item: ProviderItem,
) -> tuple[dict[str, Any], list[str]]:
    reasons: list[str] = []
    item_brands = item_brand_tokens(item)
    brand_overlap = len(quote_vehicle.brand_tokens & item.searchable_tokens)
    line_overlap = len(quote_vehicle.line_tokens & item.searchable_tokens)
    version_overlap = len(quote_vehicle.version_tokens & item.searchable_tokens)
    foreign_brand_detected = bool(item_brands) and not bool(item_brands & quote_vehicle.brand_tokens)
    vehicle_scoped = item_has_vehicle_scope(item)
    compatible = not foreign_brand_detected

    if foreign_brand_detected:
        reasons.append(
            f"Provider item points to a different brand ({', '.join(sorted(item_brands))})."
        )
        compatible = False
    elif item_brands and brand_overlap > 0:
        reasons.append("Brand text matches the requested vehicle.")

    if quote_vehicle.line_tokens and line_overlap > 0:
        reasons.append("Line text matches the requested vehicle.")
    elif vehicle_scoped and quote_vehicle.line_tokens and brand_overlap > 0:
        reasons.append("Vehicle-scoped provider item does not mention the requested line.")

    if quote_vehicle.version_tokens and version_overlap > 0:
        reasons.append("Version/trim text partially matches the requested vehicle.")

    return (
        {
            "vehicle_scoped": vehicle_scoped,
            "brand_overlap": brand_overlap,
            "line_overlap": line_overlap,
            "version_overlap": version_overlap,
            "foreign_brand_detected": foreign_brand_detected,
            "compatible": compatible,
        },
        reasons,
    )


def infer_taxonomies(*values: str | None) -> tuple[str, ...]:
    haystack = normalize_text(" ".join(value or "" for value in values))
    matches = []
    for taxonomy, keywords in TAXONOMY_KEYWORDS.items():
        for keyword in keywords:
            if normalize_text(keyword) in haystack:
                matches.append(taxonomy)
                break
    return tuple(sorted(set(matches)))


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def latest_snapshot_json(provider_dir: Path) -> Path | None:
    snapshot_root = provider_dir / "snapshots"
    if not snapshot_root.exists():
        return None
    extracted = sorted(snapshot_root.glob("*/extracted.json"))
    return extracted[-1] if extracted else None


def provider_item_notes(provider_id: str, metadata: dict[str, Any], snapshot: dict[str, Any]) -> tuple[str, ...]:
    notes = []
    note = COMMON_PROVIDER_NOTES.get(provider_id)
    if note:
        notes.append(note)
    matching_notes = metadata.get("matching", {}).get("notes")
    if matching_notes:
        notes.append(str(matching_notes))
    for value in snapshot.get("notes", []):
        notes.append(str(value))
    return tuple(dict.fromkeys(notes))


def flatten_impocali(
    metadata: dict[str, Any],
    snapshot: dict[str, Any],
) -> list[ProviderItem]:
    items: list[ProviderItem] = []
    common_notes = provider_item_notes("impocali", metadata, snapshot)
    for product_group in snapshot.get("products", []):
        taxonomy = str(product_group.get("taxonomy") or "").strip()
        taxonomy_labels = tuple(
            sorted(set(filter(None, [taxonomy, *infer_taxonomies(product_group.get("category_name"))])))
        )
        brands_by_product = product_group.get("brands_by_product", {})
        for product_name in product_group.get("product_names", []):
            product_brands = [
                str(entry.get("name"))
                for entry in brands_by_product.get(product_name, [])
                if entry.get("name")
            ]
            items.append(
                ProviderItem(
                    provider_id="impocali",
                    provider_name="Impocali",
                    provider_type="category_only",
                    detail_url=product_group.get("category_url"),
                    title=str(product_name),
                    category_name=product_group.get("category_name"),
                    subcategory_name=product_group.get("segment"),
                    brand=", ".join(product_brands) if product_brands else None,
                    reference=None,
                    sku=None,
                    supplier_item_code=None,
                    taxonomy_labels=taxonomy_labels,
                    searchable_tokens=token_set(
                        product_name,
                        product_group.get("category_name"),
                        product_group.get("segment"),
                        " ".join(product_brands),
                    ),
                    raw_match_type="category_only",
                    requires_manual_confirmation=True,
                    notes=common_notes,
                )
            )
    return items


def flatten_disfal(
    metadata: dict[str, Any],
    snapshot: dict[str, Any],
) -> list[ProviderItem]:
    items: list[ProviderItem] = []
    common_notes = provider_item_notes("disfal", metadata, snapshot)
    for family in snapshot.get("service_families", []):
        items.append(
            ProviderItem(
                provider_id="disfal",
                provider_name="Disfal",
                provider_type="category_only",
                detail_url=family.get("family_url"),
                title=str(family.get("family_name") or ""),
                category_name=family.get("family_name"),
                subcategory_name=None,
                brand=None,
                reference=None,
                sku=None,
                supplier_item_code=None,
                taxonomy_labels=tuple(
                    sorted(
                        set(
                            filter(
                                None,
                                [
                                    family.get("taxonomy_label"),
                                    *infer_taxonomies(family.get("family_name")),
                                ],
                            )
                        )
                    )
                ),
                searchable_tokens=token_set(family.get("family_name"), family.get("taxonomy_label")),
                raw_match_type=family.get("match_type"),
                requires_manual_confirmation=bool(family.get("requires_manual_confirmation", True)),
                notes=common_notes,
            )
        )

    for series in snapshot.get("service_series", []):
        title = str(series.get("heading_text") or series.get("brand_name") or "")
        brand = str(series.get("brand_name") or "") or None
        items.append(
            ProviderItem(
                provider_id="disfal",
                provider_name="Disfal",
                provider_type="category_only",
                detail_url=series.get("service_url"),
                title=title,
                category_name=series.get("service_name"),
                subcategory_name=series.get("commercial_line"),
                brand=brand,
                reference=series.get("series_label"),
                sku=None,
                supplier_item_code=None,
                taxonomy_labels=tuple(
                    sorted(
                        set(
                            filter(
                                None,
                                [
                                    series.get("taxonomy_label"),
                                    *infer_taxonomies(
                                        series.get("service_name"),
                                        series.get("commercial_line"),
                                        series.get("series_label"),
                                    ),
                                ],
                            )
                        )
                    )
                ),
                searchable_tokens=token_set(
                    title,
                    series.get("service_name"),
                    series.get("commercial_line"),
                    series.get("series_label"),
                    brand,
                ),
                raw_match_type=series.get("match_type"),
                requires_manual_confirmation=bool(series.get("requires_manual_confirmation", True)),
                notes=common_notes,
            )
        )
    return items


def flatten_parrales(
    metadata: dict[str, Any],
    snapshot: dict[str, Any],
) -> list[ProviderItem]:
    items: list[ProviderItem] = []
    common_notes = provider_item_notes("parrales", metadata, snapshot)
    for product in snapshot.get("products", []):
        items.append(
            ProviderItem(
                provider_id="parrales",
                provider_name="Parrales",
                provider_type="product_catalog",
                detail_url=product.get("product_url"),
                title=str(product.get("product_name") or ""),
                category_name=product.get("category_name"),
                subcategory_name=product.get("subcategory_name"),
                brand=product.get("brand"),
                reference=product.get("reference"),
                sku=product.get("sku"),
                supplier_item_code=None,
                taxonomy_labels=tuple(
                    sorted(
                        set(
                            filter(
                                None,
                                [
                                    *infer_taxonomies(
                                        product.get("product_name"),
                                        product.get("category_name"),
                                        product.get("subcategory_name"),
                                    )
                                ],
                            )
                        )
                    )
                ),
                searchable_tokens=frozenset(product.get("searchable_tokens", []))
                or token_set(
                    product.get("product_name"),
                    product.get("reference"),
                    product.get("sku"),
                    product.get("category_name"),
                    product.get("subcategory_name"),
                    product.get("brand"),
                ),
                raw_match_type=product.get("match_type"),
                requires_manual_confirmation=bool(product.get("requires_manual_confirmation", False)),
                notes=common_notes,
            )
        )
    return items


def flatten_repuestera(
    metadata: dict[str, Any],
    snapshot: dict[str, Any],
) -> list[ProviderItem]:
    items: list[ProviderItem] = []
    common_notes = provider_item_notes("repuestera", metadata, snapshot)
    for product in snapshot.get("products", []):
        items.append(
            ProviderItem(
                provider_id="repuestera",
                provider_name="Repuestera",
                provider_type="product_catalog",
                detail_url=product.get("detail_url"),
                title=str(product.get("product_name") or ""),
                category_name=product.get("category_name"),
                subcategory_name=None,
                brand=product.get("brand"),
                reference=product.get("reference"),
                sku=None,
                supplier_item_code=None,
                taxonomy_labels=tuple(
                    sorted(
                        set(
                            filter(
                                None,
                                [
                                    *infer_taxonomies(product.get("product_name"), product.get("category_name")),
                                ],
                            )
                        )
                    )
                ),
                searchable_tokens=frozenset(product.get("searchable_tokens", []))
                or token_set(product.get("product_name"), product.get("reference"), product.get("brand")),
                raw_match_type=product.get("match_type"),
                requires_manual_confirmation=bool(product.get("requires_manual_confirmation", False)),
                notes=common_notes,
            )
        )
    return items


def flatten_partcar(
    metadata: dict[str, Any],
    snapshot: dict[str, Any],
) -> list[ProviderItem]:
    items: list[ProviderItem] = []
    common_notes = provider_item_notes("partcar", metadata, snapshot)
    for product in snapshot.get("products", []):
        items.append(
            ProviderItem(
                provider_id="partcar",
                provider_name="Partcar",
                provider_type="product_catalog_partial",
                detail_url=product.get("detail_url"),
                title=str(product.get("product_name") or ""),
                category_name=product.get("taxonomy_label"),
                subcategory_name=None,
                brand=None,
                reference=None,
                sku=None,
                supplier_item_code=product.get("supplier_item_code"),
                taxonomy_labels=tuple(
                    sorted(
                        set(
                            filter(
                                None,
                                [
                                    product.get("taxonomy_label"),
                                    *infer_taxonomies(product.get("product_name")),
                                ],
                            )
                        )
                    )
                ),
                searchable_tokens=frozenset(product.get("searchable_tokens", []))
                or token_set(product.get("product_name"), product.get("supplier_item_code")),
                raw_match_type=product.get("match_type"),
                requires_manual_confirmation=bool(product.get("requires_manual_confirmation", True)),
                notes=common_notes,
            )
        )
    return items


FLATTENERS = {
    "disfal": flatten_disfal,
    "impocali": flatten_impocali,
    "parrales": flatten_parrales,
    "partcar": flatten_partcar,
    "repuestera": flatten_repuestera,
}


def load_provider_catalog_index(providers_root: Path = DEFAULT_PROVIDERS_ROOT) -> CatalogIndex:
    items: list[ProviderItem] = []
    provider_specs: dict[str, dict[str, Any]] = {}

    if not providers_root.exists():
        return CatalogIndex(
            items=[],
            provider_specs={},
            references=defaultdict(set),
            tokens=defaultdict(set),
            taxonomies=defaultdict(set),
        )

    for provider_dir in sorted(providers_root.iterdir()):
        if not provider_dir.is_dir():
            continue
        provider_id = provider_dir.name
        metadata_path = provider_dir / "provider.json"
        snapshot_path = latest_snapshot_json(provider_dir)
        flattener = FLATTENERS.get(provider_id)
        if not metadata_path.exists() or snapshot_path is None or flattener is None:
            continue
        metadata = load_json(metadata_path)
        snapshot = load_json(snapshot_path)
        provider_specs[provider_id] = {
            "provider_id": provider_id,
            "display_name": metadata.get("display_name", provider_id.title()),
            "website": metadata.get("website"),
            "matching": metadata.get("matching", {}),
            "data_precision": metadata.get("data_precision", {}),
            "snapshot_date": snapshot.get("snapshot_date"),
            "snapshot_path": str(snapshot_path),
            "notes": list(provider_item_notes(provider_id, metadata, snapshot)),
        }
        items.extend(flattener(metadata, snapshot))

    references: dict[str, set[int]] = defaultdict(set)
    tokens: dict[str, set[int]] = defaultdict(set)
    taxonomies: dict[str, set[int]] = defaultdict(set)
    for index, item in enumerate(items):
        for candidate_ref in (item.reference, item.sku, item.supplier_item_code):
            normalized_ref = normalize_reference(candidate_ref)
            if normalized_ref:
                references[normalized_ref].add(index)
        for token in item.searchable_tokens:
            tokens[token].add(index)
        for taxonomy in item.taxonomy_labels:
            taxonomies[taxonomy].add(index)

    return CatalogIndex(
        items=items,
        provider_specs=provider_specs,
        references=references,
        tokens=tokens,
        taxonomies=taxonomies,
    )


def overlap_score(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(len(left), 1)


def pick_candidate_ids(
    index: CatalogIndex,
    requested_reference: str | None,
    part_tokens: frozenset[str],
    vehicle_tokens: frozenset[str],
    requested_taxonomies: tuple[str, ...],
) -> set[int]:
    candidate_ids: set[int] = set()
    if requested_reference:
        candidate_ids.update(index.references.get(requested_reference, set()))
    for taxonomy in requested_taxonomies:
        candidate_ids.update(index.taxonomies.get(taxonomy, set()))
    for token in part_tokens:
        candidate_ids.update(index.tokens.get(token, set()))
    for token in vehicle_tokens:
        candidate_ids.update(index.tokens.get(token, set()))
    return candidate_ids


def infer_match_type(
    requested_reference: str | None,
    score: int,
    exact_reference_hit: bool,
    vehicle_overlap: int,
    taxonomy_overlap: bool,
    provider_id: str,
    brand_overlap: int,
    line_overlap: int,
) -> str:
    if exact_reference_hit:
        return "exact_reference"
    if provider_id in {"impocali", "disfal"}:
        return "manual_confirmation_required"
    if brand_overlap > 0 and line_overlap > 0 and taxonomy_overlap and score >= 70:
        return "vehicle_compatible"
    if vehicle_overlap > 0 and taxonomy_overlap and score >= 70:
        return "vehicle_compatible"
    if taxonomy_overlap and score >= 35:
        return "category_only"
    if requested_reference and score >= 50:
        return "manual_confirmation_required"
    return "manual_confirmation_required"


def score_item(
    part_name: str,
    requested_reference: str | None,
    part_tokens: frozenset[str],
    quote_vehicle: VehicleProfile,
    requested_taxonomies: tuple[str, ...],
    item: ProviderItem,
) -> tuple[int, list[str], str]:
    reasons: list[str] = []
    exact_reference_hit = False
    normalized_item_refs = {
        value
        for value in (
            normalize_reference(item.reference),
            normalize_reference(item.sku),
            normalize_reference(item.supplier_item_code),
        )
        if value
    }
    taxonomy_overlap = bool(set(requested_taxonomies) & set(item.taxonomy_labels))
    token_overlap_value = overlap_score(part_tokens, item.searchable_tokens)
    part_overlap_tokens = part_tokens & item.searchable_tokens
    query_signal = infer_primary_part_signal(part_name)
    item_signal = infer_primary_part_signal(
        item.title,
        item.category_name,
        item.subcategory_name,
        " ".join(item.taxonomy_labels),
    )
    vehicle_tokens = (
        quote_vehicle.brand_tokens | quote_vehicle.line_tokens | quote_vehicle.version_tokens
    )
    vehicle_overlap = len(vehicle_tokens & item.searchable_tokens)
    title_similarity = SequenceMatcher(None, normalize_text(part_name), normalize_text(item.title)).ratio()
    compatibility, compatibility_reasons = vehicle_compatibility(quote_vehicle, item)
    reasons.extend(compatibility_reasons)

    score = 0
    if requested_reference and requested_reference in normalized_item_refs:
        exact_reference_hit = True
        score = 100
        reasons.append(f"Exact reference match: {requested_reference}")
    elif requested_reference and requested_reference in item.searchable_tokens:
        score = 95
        reasons.append(f"Reference token was found in provider text: {requested_reference}")
    else:
        if not compatibility["compatible"]:
            return 0, reasons, "manual_confirmation_required"
        if (
            query_signal
            and item_signal
            and item_signal not in PART_SIGNAL_COMPATIBILITY.get(query_signal, {query_signal})
        ):
            reasons.append(
                f"Candidate part type ({item_signal}) does not match the requested part type ({query_signal})."
            )
            return 0, reasons, "manual_confirmation_required"
        signal_points = part_signal_points(query_signal, item_signal)
        if part_tokens and not part_overlap_tokens and item.provider_type != "category_only" and signal_points <= 0:
            reasons.append("Candidate does not share any relevant part-name tokens.")
            return 0, reasons, "manual_confirmation_required"
        if taxonomy_overlap:
            score += 30
            reasons.append("Taxonomy/family looks compatible.")
        if signal_points > 0:
            score += signal_points
            reasons.append(f"Part-type compatibility contributes {signal_points} points.")
        if token_overlap_value > 0:
            token_points = round(token_overlap_value * 45)
            score += token_points
            reasons.append(f"Part-name token overlap contributes {token_points} points.")
        if title_similarity >= 0.25:
            name_points = round(title_similarity * 20)
            score += name_points
            reasons.append(f"Product-name similarity contributes {name_points} points.")
        if compatibility["brand_overlap"] > 0:
            brand_points = min(compatibility["brand_overlap"] * 12, 24)
            score += brand_points
            reasons.append(f"Brand compatibility contributes {brand_points} points.")
        if compatibility["line_overlap"] > 0:
            line_points = min(compatibility["line_overlap"] * 10, 20)
            score += line_points
            reasons.append(f"Line compatibility contributes {line_points} points.")
        if compatibility["version_overlap"] > 0:
            version_points = min(compatibility["version_overlap"] * 4, 12)
            score += version_points
            reasons.append(f"Version compatibility contributes {version_points} points.")
        if vehicle_overlap > 0:
            vehicle_points = min(vehicle_overlap * 3, 9)
            score += vehicle_points
            reasons.append(f"Vehicle text overlap contributes {vehicle_points} points.")
        if compatibility["vehicle_scoped"] and quote_vehicle.brand_tokens and compatibility["brand_overlap"] <= 0:
            score = min(score, 10)
            reasons.append("Vehicle-scoped candidate was capped because the requested brand is missing.")
        if (
            compatibility["vehicle_scoped"]
            and quote_vehicle.line_tokens
            and compatibility["brand_overlap"] > 0
            and compatibility["line_overlap"] <= 0
        ):
            score = min(score, 18)
            reasons.append(
                "Vehicle-scoped candidate was capped because the requested line is missing."
            )
        if (
            compatibility["vehicle_scoped"]
            and quote_vehicle.version_tokens
            and compatibility["brand_overlap"] > 0
            and compatibility["line_overlap"] > 0
            and compatibility["version_overlap"] <= 0
        ):
            score = min(score, 68)
            reasons.append(
                "Vehicle-scoped candidate keeps only a partial score because the requested version is missing."
            )

    if item.provider_id in {"impocali", "disfal"}:
        score = min(score, 55 if taxonomy_overlap else 25)
    elif item.provider_id == "partcar":
        score = min(score, 78 if taxonomy_overlap else 60)
    elif not exact_reference_hit and requested_reference is None:
        score = min(score, 88)

    if score < 20:
        return 0, reasons, "manual_confirmation_required"

    match_type = infer_match_type(
        requested_reference=requested_reference,
        score=score,
        exact_reference_hit=exact_reference_hit,
        vehicle_overlap=vehicle_overlap,
        taxonomy_overlap=taxonomy_overlap,
        provider_id=item.provider_id,
        brand_overlap=compatibility["brand_overlap"],
        line_overlap=compatibility["line_overlap"],
    )
    return max(0, min(score, 100)), reasons, match_type


def summarize_match(item: ProviderItem, score: int, match_type: str) -> str:
    if item.provider_id in {"impocali", "disfal"}:
        return (
            f"{item.provider_name} no expone referencia exacta publica; "
            f"la coincidencia es por familia/categoria ({score}%)."
        )
    if match_type == "exact_reference":
        return f"{item.provider_name} muestra una referencia exacta compatible ({score}%)."
    if match_type == "vehicle_compatible":
        return f"{item.provider_name} parece compatible por texto vehicular y tipo de repuesto ({score}%)."
    if item.provider_id == "partcar":
        return (
            f"{item.provider_name} ofrece una coincidencia probable por descripcion y categoria, "
            f"pero requiere validar su codigo interno ({score}%)."
        )
    return f"{item.provider_name} ofrece una coincidencia parcial por nombre/categoria ({score}%)."


def build_match_entry(
    item: ProviderItem,
    score: int,
    match_type: str,
    reasons: list[str],
) -> dict[str, Any]:
    return {
        "provider_id": item.provider_id,
        "provider_name": item.provider_name,
        "score_percent": score,
        "match_type": match_type,
        "detail_url": item.detail_url,
        "product_name": item.title,
        "reference": item.reference,
        "sku": item.sku,
        "supplier_item_code": item.supplier_item_code,
        "brand": item.brand,
        "category_name": item.category_name,
        "subcategory_name": item.subcategory_name,
        "taxonomy_labels": list(item.taxonomy_labels),
        "requires_manual_confirmation": item.requires_manual_confirmation or match_type != "exact_reference",
        "summary": summarize_match(item, score, match_type),
        "notes": list(item.notes),
        "reasons": reasons,
    }


def dedupe_match_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for entry in entries:
        dedupe_key = (
            str(entry.get("provider_id") or ""),
            normalize_text(entry.get("product_name")),
            normalize_reference(entry.get("reference")) or "",
            normalize_reference(entry.get("sku")) or "",
            normalize_reference(entry.get("supplier_item_code")) or "",
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(entry)
    return deduped


def match_quote_part(
    part: dict[str, Any],
    quote_context: dict[str, Any],
    index: CatalogIndex,
    limit: int = 5,
) -> dict[str, Any]:
    part_name = str(part.get("name") or "").strip()
    requested_reference = normalize_reference(part.get("reference"))
    part_tokens = part_query_tokens(part_name, part.get("reference"))
    quote_vehicle = vehicle_profile_from_quote_context(quote_context)
    vehicle_tokens = (
        quote_vehicle.brand_tokens | quote_vehicle.line_tokens | quote_vehicle.version_tokens
    ) | token_set(quote_context.get("ano"))
    requested_taxonomies = infer_taxonomies(part_name, part.get("reference"))

    candidate_ids = pick_candidate_ids(
        index=index,
        requested_reference=requested_reference,
        part_tokens=part_tokens,
        vehicle_tokens=vehicle_tokens,
        requested_taxonomies=requested_taxonomies,
    )

    scored_matches: list[dict[str, Any]] = []
    for candidate_id in candidate_ids:
        item = index.items[candidate_id]
        score, reasons, match_type = score_item(
            part_name=part_name,
            requested_reference=requested_reference,
            part_tokens=part_tokens,
            quote_vehicle=quote_vehicle,
            requested_taxonomies=requested_taxonomies,
            item=item,
        )
        if score <= 0:
            continue
        scored_matches.append(build_match_entry(item, score, match_type, reasons))

    scored_matches.sort(
        key=lambda entry: (
            entry["score_percent"],
            1 if entry["match_type"] == "exact_reference" else 0,
            entry["provider_name"],
            entry["product_name"],
        ),
        reverse=True,
    )
    scored_matches = dedupe_match_entries(scored_matches)
    best = scored_matches[0] if scored_matches else None
    return {
        "part_name": part_name,
        "requested_reference": part.get("reference"),
        "reference_validation_text": part.get("reference_validation_text"),
        "quantity": part.get("quantity"),
        "requested_taxonomies": list(requested_taxonomies),
        "best_score_percent": best.get("score_percent", 0) if best else 0,
        "best_match_type": best.get("match_type") if best else None,
        "best_provider_id": best.get("provider_id") if best else None,
        "matches": scored_matches[:limit],
    }


def build_quote_match_report(
    quote_payload: dict[str, Any],
    index: CatalogIndex,
    limit_per_part: int = 5,
) -> dict[str, Any]:
    orbika = quote_payload.get("orbika", {})
    quote_context = {
        "marca": orbika.get("marca"),
        "linea": orbika.get("linea"),
        "version": orbika.get("version"),
        "ano": orbika.get("ano"),
        "placa": orbika.get("placa"),
        "vin": orbika.get("vin"),
    }
    part_reports = [
        match_quote_part(part, quote_context, index, limit=limit_per_part)
        for part in orbika.get("parts", [])
    ]

    provider_hits: dict[str, int] = defaultdict(int)
    exact_matches = 0
    partial_matches = 0
    manual_only = 0
    matched_parts = 0
    for part_report in part_reports:
        if not part_report["matches"]:
            continue
        matched_parts += 1
        best = part_report["matches"][0]
        provider_hits[best["provider_id"]] += 1
        if best["match_type"] == "exact_reference":
            exact_matches += 1
        elif best["match_type"] in {"category_only", "vehicle_compatible"}:
            partial_matches += 1
        else:
            manual_only += 1

    provider_specs = [
        index.provider_specs[provider_id]
        for provider_id in sorted(provider_hits)
        if provider_id in index.provider_specs
    ]

    return {
        "generated_at": utc_now(),
        "provider_snapshot_dates": {
            provider_id: spec.get("snapshot_date")
            for provider_id, spec in sorted(index.provider_specs.items())
        },
        "summary": {
            "parts_total": len(part_reports),
            "parts_with_matches": matched_parts,
            "exact_reference_matches": exact_matches,
            "partial_matches": partial_matches,
            "manual_confirmation_only": manual_only,
            "provider_hits": dict(sorted(provider_hits.items())),
        },
        "provider_specs": provider_specs,
        "parts": part_reports,
    }


def extract_quote_date(quote_payload: dict[str, Any]) -> str:
    received_at = str(quote_payload.get("source", {}).get("received_at") or "").strip()
    if received_at:
        return received_at[:10]
    generated_at = str(quote_payload.get("generated_at") or "").strip()
    return generated_at[:10] if generated_at else "unknown-date"


def enrich_quote_payload(
    quote_payload: dict[str, Any],
    index: CatalogIndex,
    limit_per_part: int = 5,
) -> dict[str, Any]:
    quote_payload["supplier_matching"] = build_quote_match_report(
        quote_payload=quote_payload,
        index=index,
        limit_per_part=limit_per_part,
    )
    return quote_payload


def write_quote_payload(path: Path, quote_payload: dict[str, Any]) -> None:
    compact_payload = compact_quote_payload_for_storage(quote_payload)
    path.write_text(json.dumps(compact_payload, indent=2, ensure_ascii=False), encoding="utf-8")


def rebuild_daily_reports(quotes_dir: Path, daily_dir: Path) -> list[Path]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for quote_path in sorted(quotes_dir.glob("*.json")):
        payload = load_json(quote_path)
        grouped[extract_quote_date(payload)].append(payload)

    written_paths: list[Path] = []
    daily_dir.mkdir(parents=True, exist_ok=True)
    for date, quotes in grouped.items():
        quotes_summary = []
        providers_seen: dict[str, dict[str, Any]] = {}
        for quote in quotes:
            matching = quote.get("supplier_matching", {})
            summary = matching.get("summary", {})
            for spec in matching.get("provider_specs", []):
                providers_seen[spec["provider_id"]] = spec
            quotes_summary.append(
                {
                    "quote_key": quote.get("quote_key"),
                    "aviso_id": quote.get("orbika", {}).get("aviso_id"),
                    "placa": quote.get("orbika", {}).get("placa"),
                    "subject": quote.get("source", {}).get("subject"),
                    "parts_total": summary.get("parts_total", 0),
                    "parts_with_matches": summary.get("parts_with_matches", 0),
                    "exact_reference_matches": summary.get("exact_reference_matches", 0),
                    "provider_hits": summary.get("provider_hits", {}),
                }
            )

        json_path = daily_dir / f"{date}.json"
        md_path = daily_dir / f"{date}.md"
        payload = {
            "date": date,
            "generated_at": utc_now(),
            "quotes": quotes_summary,
            "provider_specs": [providers_seen[key] for key in sorted(providers_seen)],
        }
        json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

        md_lines = [
            f"# Daily Supplier Matching Report {date}",
            "",
            f"- Quotes: {len(quotes_summary)}",
            f"- Providers with hits: {len(providers_seen)}",
            "",
        ]
        for quote_summary in quotes_summary:
            md_lines.extend(
                [
                    f"## {quote_summary['subject']}",
                    "",
                    f"- Quote key: `{quote_summary['quote_key']}`",
                    f"- Aviso: `{quote_summary['aviso_id'] or 'n/a'}`",
                    f"- Placa: `{quote_summary['placa'] or 'n/a'}`",
                    f"- Parts total: {quote_summary['parts_total']}",
                    f"- Parts with matches: {quote_summary['parts_with_matches']}",
                    f"- Exact reference matches: {quote_summary['exact_reference_matches']}",
                    f"- Provider hits: {json.dumps(quote_summary['provider_hits'], ensure_ascii=False)}",
                    "",
                ]
            )
        md_path.write_text("\n".join(md_lines), encoding="utf-8")
        written_paths.extend([json_path, md_path])

    return written_paths


def enrich_quotes_dir(
    quotes_dir: Path,
    providers_root: Path = DEFAULT_PROVIDERS_ROOT,
    daily_dir: Path | None = DEFAULT_DAILY_REPORT_DIR,
    limit_per_part: int = 5,
) -> dict[str, Any]:
    index = load_provider_catalog_index(providers_root)
    enriched = 0
    for quote_path in sorted(quotes_dir.glob("*.json")):
        payload = load_json(quote_path)
        enrich_quote_payload(payload, index=index, limit_per_part=limit_per_part)
        write_quote_payload(quote_path, payload)
        enriched += 1

    daily_paths = rebuild_daily_reports(quotes_dir, daily_dir) if daily_dir else []
    return {
        "quotes_enriched": enriched,
        "daily_reports_written": [str(path) for path in daily_paths],
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Attach local supplier matches to saved Orbika quotes.")
    parser.add_argument("--quotes-dir", type=Path, default=DEFAULT_QUOTES_DIR)
    parser.add_argument("--providers-root", type=Path, default=DEFAULT_PROVIDERS_ROOT)
    parser.add_argument("--daily-report-dir", type=Path, default=DEFAULT_DAILY_REPORT_DIR)
    parser.add_argument("--limit-per-part", type=int, default=5)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    result = enrich_quotes_dir(
        quotes_dir=args.quotes_dir,
        providers_root=args.providers_root,
        daily_dir=args.daily_report_dir,
        limit_per_part=args.limit_per_part,
    )
    print(
        "Supplier matching completed: "
        f"{result['quotes_enriched']} quote file(s) enriched. "
        f"Daily reports: {len(result['daily_reports_written'])}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
