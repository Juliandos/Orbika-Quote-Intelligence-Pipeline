#!/usr/bin/env python3
"""Local supplier matching for extracted Orbika quotes."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from tools.customer_preference_store import load_customer_preferences_for_quote
from tools.postgres_quote_persistence import database_url_from_env


DEFAULT_PROVIDERS_ROOT = Path("supplier_catalog/providers")

DEFAULT_PROVIDER_CATALOG_DB_URL = (
    f"postgresql://{os.environ.get('ORBIKA_POSTGRES_USER', 'orbika')}:"
    f"{os.environ.get('ORBIKA_POSTGRES_PASSWORD', 'orbika_local_dev_password')}@"
    f"localhost:{os.environ.get('ORBIKA_POSTGRES_PORT', '5433')}/"
    f"{os.environ.get('ORBIKA_POSTGRES_DB', 'orbika_local')}"
)


def resolve_provider_catalog_database_url() -> str:
    return database_url_from_env() or DEFAULT_PROVIDER_CATALOG_DB_URL

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
    "completa",
    "completo",
    "delantera",
    "delantero",
    "derecha",
    "derecho",
    "exterior",
    "ext",
    "frontal",
    "inferior",
    "inner",
    "inside",
    "interior",
    "izquierda",
    "izquierdo",
    "base",
    "guia",
    "lado",
    "porta",
    "left",
    "soporte",
    "marca",
    "plastico",
    "plastico",
    "rear",
    "repuesto",
    "right",
    "superior",
    "trasera",
    "trasero",
}

YEAR_RANGE_PATTERN = re.compile(r"(?<!\d)(20\d{2})\s*[-/]\s*(20\d{2})(?!\d)")
YEAR_PATTERN = re.compile(r"(?<!\d)(20\d{2})(?!\d)")

SIDE_TOKEN_GROUPS: dict[str, frozenset[str]] = {
    "left": frozenset({"izquierda", "izquierdo", "left", "lh"}),
    "right": frozenset({"derecha", "derecho", "right", "rh"}),
}

POSITION_TOKEN_GROUPS: dict[str, frozenset[str]] = {
    "front": frozenset({"delantera", "delantero", "front", "frontal"}),
    "rear": frozenset({"trasera", "trasero", "rear", "posterior"}),
    "inner": frozenset({"interior", "inside", "inner"}),
    "outer": frozenset({"exterior", "outside", "outer"}),
    "upper": frozenset({"superior", "upper"}),
    "lower": frozenset({"inferior", "lower"}),
}

PRESENTATION_TOKEN_GROUPS: dict[str, frozenset[str]] = {
    "kit": frozenset({"kit", "juego", "set", "combo"}),
    "unit": frozenset({"unidad", "unitario", "unit", "individual"}),
}

COLOR_TOKEN_GROUPS: dict[str, frozenset[str]] = {
    "black": frozenset({"negro", "negra", "black"}),
    "white": frozenset({"blanco", "blanca", "white"}),
    "red": frozenset({"rojo", "roja", "red"}),
    "blue": frozenset({"azul", "blue"}),
    "gray": frozenset({"gris", "grisaceo", "silver", "plata", "gray", "grey"}),
    "green": frozenset({"verde", "green"}),
}

FINISH_TOKEN_GROUPS: dict[str, frozenset[str]] = {
    "chrome": frozenset({"cromado", "chrome"}),
    "matte": frozenset({"mate", "matte"}),
    "painted": frozenset({"pintado", "pintada", "painted", "imprimado", "primer"}),
    "textured": frozenset({"texturizado", "texturizada", "textured"}),
    "gloss": frozenset({"brillante", "brilloso", "gloss"}),
}

HARD_CONFLICT_RISK_FLAGS = frozenset({"side_mismatch", "position_mismatch", "presentation_mismatch"})
SOFT_WARNING_SCORE_CAPS: dict[str, int] = {
    "year_mismatch": 45,
    "color_mismatch": 60,
    "finish_mismatch": 58,
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
        "guardabarro",
        "estribo",
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
    "tires_wheels": [
        "llanta",
        "llantas",
        "neumatico",
        "neumaticos",
        "rin",
        "rines",
        "tire",
        "tires",
        "wheel",
        "wheels",
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
        "kit plumillas",
        "limpiaparabrisas",
        "limpiavidrio",
        "plumilla",
        "plumillas",
        "escobilla",
        "escobillas",
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
            "product_name": entry.get("product_name"),
            "score_percent": entry.get("score_percent"),
            "match_type": entry.get("match_type"),
            "detail_url": entry.get("detail_url"),
            "part_name": entry.get("part_name"),
            "reference": entry.get("reference"),
            "sku": entry.get("sku"),
            "brand": entry.get("brand"),
            "category_name": entry.get("category_name"),
            "subcategory_name": entry.get("subcategory_name"),
            "risk_flags": entry.get("risk_flags"),
            "compatibility_warnings": entry.get("compatibility_warnings"),
            "preference_notes": entry.get("preference_notes"),
            "compatibility_state": entry.get("compatibility_state"),
            "compatibility_summary": entry.get("compatibility_summary"),
            "operational_note": entry.get("operational_note"),
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
            "catalog": report.get("catalog"),
            "summary": compact_supplier_summary_for_storage(report.get("summary", {})),
            "provider_specs": [
                compact_provider_spec_for_storage(spec)
                for spec in report.get("provider_specs", [])
            ],
            "preferences": report.get("preferences"),
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
            "compatibility_state": entry.get("compatibility_state"),
            "compatibility_summary": entry.get("compatibility_summary"),
            "compatibility_warnings": entry.get("compatibility_warnings"),
            "preference_notes": entry.get("preference_notes"),
            "risk_flags": entry.get("risk_flags"),
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
            "review_status": part.get("review_status"),
            "risk_notes": part.get("risk_notes"),
            "preference_notes": part.get("preference_notes"),
            "internet_query": part.get("internet_query"),
            "internet_summary_comment": part.get("internet_summary_comment"),
            "internet_matches": [
                compact_agentic_match_for_storage(match)
                for match in part.get("internet_matches", [])
            ],
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
            "internet_search": report.get("internet_search"),
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
            "gmail_id": source.get("gmail_id"),
            "message_id": source.get("message_id"),
            "internal_date_ms": source.get("internal_date_ms"),
            "received_at": source.get("received_at"),
            "sender": source.get("sender"),
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

PART_FAMILY_PRIORITY = (
    "tailgate_complete",
    "tailgate_trim",
    "tailgate_emblem",
    "tailgate_decal",
    "tailgate_handle",
    "tailgate_shock",
    "bumper_absorber",
    "bumper_support",
    "bumper_clip",
    "bumper_lamp",
    "bumper_cover",
    "hood_hinge",
    "hood",
    "front_fender",
    "side_step_trim",
    "wheel_well_liner",
    "wiper_kit",
    "engine_oil",
    "coolant_fluid",
    "oil_filter",
    "cabin_filter",
    "windshield_seal",
    "windshield_wiper_arm",
    "windshield_glass",
    "headlamp_support",
    "headlamp_harness",
    "headlamp_bulb",
    "headlamp_foglamp_base",
    "headlamp_foglamp",
    "headlamp",
    "body_panel",
    "speaker_audio",
    "horn_mount",
    "horn",
    "radiator_hose",
    "radiator_cap",
    "radiator_fan",
    "radiator",
    "rearview_mirror_glass",
    "rearview_mirror_cover",
    "rearview_mirror_base",
    "rearview_mirror",
    "wheel_valve",
    "wheel_bearing",
    "wheel_rim",
    "spare_tire_cover",
    "cylinder_head_gasket",
    "cylinder_head",
    "spark_plug",
    "fuel_pump",
    "sensor",
    "hose",
    "gasket",
    "bearing",
    "nut_bolt",
    "tire",
)

PART_FAMILY_PATTERNS: dict[str, tuple[str, ...]] = {
    "tailgate_complete": (
        "compuerta trasera completa",
        "compuerta completa",
        "porton trasero completo",
        "compuerta baul completa",
    ),
    "tailgate_trim": (
        "tapizado compuerta",
        "forro compuerta",
        "tapizado puerta trasera",
        "tapizado porton",
    ),
    "tailgate_emblem": (
        "emblema compuerta",
        "emblema marca compuerta",
        "logo compuerta",
        "insignia compuerta",
    ),
    "tailgate_decal": (
        "calcomania compuerta",
        "sticker compuerta",
        "adhesivo compuerta",
    ),
    "tailgate_handle": (
        "manija compuerta",
        "chapeta compuerta",
        "manija porton",
    ),
    "tailgate_shock": (
        "amortiguador compuerta",
        "resorte compuerta",
        "piston compuerta",
    ),
    "bumper_absorber": (
        "absorbedor de impacto",
        "absorbedor impacto",
        "absorbedor central bomper",
        "absorbedor central bumper",
        "absorbedor bomper",
        "absorbedor bumper",
    ),
    "bumper_support": (
        "guia soporte bomper",
        "guia soporte bumper",
        "guia bomper",
        "guia bumper",
        "soporte bomper",
        "soporte bumper",
        "soporte parachoque",
    ),
    "bumper_clip": (
        "clip bomper",
        "clip bumper",
        "grapa bomper",
        "grapa bumper",
        "pin bomper",
        "pin bumper",
        "presion bomper",
        "presion bumper",
    ),
    "bumper_lamp": (
        "lampara bomper",
        "lampara bumper",
        "faro bomper",
        "faro bumper",
        "exploradora bumper",
        "exploradora bomper",
    ),
    "bumper_cover": (
        "bomper",
        "bumper",
        "parachoque",
    ),
    "hood_hinge": (
        "bisagra del capo",
        "bisagra de capo",
        "bisagra capo",
        "bisagra del capot",
        "bisagra de capot",
        "bisagra capot",
    ),
    "hood": (
        "capo",
        "capot",
    ),
    "front_fender": (
        "guardafango",
        "guardabarro",
        "aleta",
        "fender",
    ),
    "side_step_trim": (
        "bocel estribo",
        "estribo",
        "moldura estribo",
        "running board",
        "side step",
    ),
    "wheel_well_liner": (
        "guardapolvo plastico",
        "guardapolvo",
        "paso de rueda",
        "paso rueda",
        "cubre rueda",
        "liner rueda",
    ),
    "wiper_kit": (
        "kit plumillas",
        "kit limpiaparabrisas",
        "juego plumillas",
        "juego limpiaparabrisas",
    ),
    "engine_oil": (
        "aceite motor",
        "aceite 1 4",
        "aceite cuarto",
        "aceite de motor",
        "engine oil",
    ),
    "coolant_fluid": (
        "liquido refrigerante",
        "liquido enfriante",
        "refrigerante motor",
        "anticongelante",
        "coolant",
    ),
    "oil_filter": (
        "filtro de aceite",
        "filtro aceite",
        "oil filter",
    ),
    "cabin_filter": (
        "filtro aire acondicionado",
        "filtro de aire acondicionado",
        "filtro habitaculo",
        "filtro de aire",
        "filtro aire",
        "cabin filter",
    ),
    "windshield_seal": (
        "empaque vidrio parabrisas",
        "empaque parabrisas",
        "sello parabrisas",
        "caucho parabrisas",
        "empaque vidrio trasero",
        "empaque vidrio posterior",
    ),
    "windshield_wiper_arm": (
        "brazo limpiabrisas",
        "brazo limpiaparabrisas",
    ),
    "windshield_glass": (
        "parabrisas",
        "vidrio panoramico",
        "vidrio delantero",
    ),
    "headlamp_support": (
        "soporte farola",
        "soporte faro",
        "base farola",
        "base faro",
    ),
    "headlamp_harness": (
        "arnes farola",
        "arnes faro",
        "cable farola",
        "cable faro",
    ),
    "headlamp_bulb": (
        "bombillo",
        "bombillos",
        "bulbo",
        "bulbos",
    ),
    "headlamp_foglamp_base": (
        "base exploradora",
        "soporte exploradora",
        "base farola exploradora",
        "base antiniebla",
    ),
    "headlamp_foglamp": (
        "exploradora",
        "exploradoras",
        "antiniebla",
        "fog lamp",
    ),
    "headlamp": (
        "faro",
        "faro delantero",
        "farola",
        "farola delantera",
    ),
    "body_panel": (
        "bocel",
        "bomper",
        "bumper",
        "compuerta",
        "guia lateral",
        "panel",
        "parachoque",
        "puerta",
        "spoiler",
    ),
    "speaker_audio": (
        "alto parlante",
        "alto parlantes",
        "parlante",
        "parlantes",
        "tweeter",
        "tweeters",
    ),
    "horn_mount": (
        "porta bocin",
        "porta bocina",
        "soporte bocin",
        "soporte bocina",
    ),
    "horn": (
        "bocin",
        "bocina",
        "claxon",
    ),
    "radiator_hose": (
        "manguera radiador",
        "manguera refrigerante",
        "manguera calefaccion",
    ),
    "radiator_cap": ("tapa radiador",),
    "radiator_fan": (
        "electroventilador",
        "ventilador radiador",
        "abanico radiador",
    ),
    "radiator": ("radiador",),
    "rearview_mirror_glass": (
        "luna espejo",
        "vidrio espejo",
        "cristal espejo",
    ),
    "rearview_mirror_cover": (
        "carcasa espejo",
        "tapa espejo",
        "cobertor espejo",
    ),
    "rearview_mirror_base": (
        "base espejo",
        "soporte espejo",
    ),
    "rearview_mirror": (
        "espejo exterior",
        "espejo electrico",
        "espejo lateral",
        "espejo retrovisor",
        "retrovisor electrico",
        "retrovisor",
    ),
    "wheel_valve": (
        "valvula rin",
        "valvula llanta",
        "valvula rueda",
    ),
    "wheel_bearing": (
        "rodamiento rueda",
        "balinera rueda",
        "cubo rueda",
    ),
    "wheel_rim": (
        "rin",
        "rines",
        "aro",
        "aros",
    ),
    "spare_tire_cover": (
        "protector plastico ext llanta repuesto",
        "protector plastico llanta repuesto",
        "protector llanta repuesto",
        "cobertor llanta repuesto",
        "forro llanta repuesto",
    ),
    "cylinder_head_gasket": (
        "empaque culata",
        "juego empaque culata",
        "empaque cabezote",
    ),
    "cylinder_head": (
        "culata",
        "cabezote",
    ),
    "spark_plug": (
        "bujia",
        "bujias",
    ),
    "fuel_pump": (
        "bomba de combustible",
        "bomba gasolina",
        "bomba de gasolina",
    ),
    "sensor": (
        "sensor",
        "sensores",
    ),
    "hose": (
        "manguera",
        "mangueras",
    ),
    "gasket": (
        "empaque",
        "empaques",
        "sello",
        "sellos",
        "reten",
        "retenes",
    ),
    "bearing": (
        "rodamiento",
        "rodamientos",
        "balinera",
        "balineras",
    ),
    "nut_bolt": (
        "tuerca",
        "tuercas",
        "perno",
        "pernos",
        "tornillo",
        "tornillos",
    ),
    "tire": (
        "llanta",
        "llantas",
        "neumatico",
        "neumaticos",
    ),
}

GENERIC_PART_FAMILIES = frozenset({"gasket", "bearing", "nut_bolt", "tire"})
BRAND_FLEXIBLE_FAMILIES = frozenset({"gasket", "bearing", "nut_bolt", "tire"})

# Specific commercial families cannot be bridged by vehicle or taxonomy overlap.
STRICT_PART_FAMILIES = frozenset({
    "tailgate_complete", "tailgate_trim", "tailgate_emblem", "tailgate_decal",
    "tailgate_handle", "tailgate_shock", "bumper_absorber", "bumper_support",
    "bumper_clip", "bumper_lamp", "bumper_cover", "hood_hinge",
    "side_step_trim", "wheel_well_liner", "wiper_kit", "engine_oil",
    "coolant_fluid", "oil_filter", "cabin_filter", "windshield_seal",
    "headlamp_support", "headlamp_foglamp_base", "headlamp_foglamp",
    "headlamp", "speaker_audio", "horn_mount", "horn",
})

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
    "procar": (
        "Procar se apoya en catalogo autos y detalle de producto; el home modal es de bajo riesgo, "
        "pero la validacion debe hacerse desde las paginas de catalogo y detalle."
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
    source: str = "unknown"
    source_detail: str | None = None


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
    merged = " ".join("" if value is None else str(value) for value in values)
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


def infer_part_family(*values: str | None) -> str | None:
    normalized_text = normalize_text(" ".join(value or "" for value in values))
    normalized_tokens = token_set(*values)
    for family in PART_FAMILY_PRIORITY:
        for pattern in PART_FAMILY_PATTERNS.get(family, ()):
            if text_contains_pattern(normalized_text, normalized_tokens, pattern):
                return family
    return None


def part_family_is_compatible(
    requested_family: str | None,
    candidate_family: str | None,
) -> bool:
    if not requested_family or not candidate_family:
        return True
    if requested_family == candidate_family:
        return True
    if requested_family in STRICT_PART_FAMILIES and candidate_family in STRICT_PART_FAMILIES:
        return False
    if requested_family in STRICT_PART_FAMILIES and candidate_family in {"body_panel", "filter", "gasket", "hose"}:
        return False
    if requested_family == "body_panel" and candidate_family in {
        "bumper_absorber",
        "bumper_support",
        "bumper_clip",
        "bumper_lamp",
        "bumper_cover",
        "hood_hinge",
        "hood",
        "front_fender",
        "side_step_trim",
        "wheel_well_liner",
        "tailgate_complete",
        "tailgate_trim",
        "tailgate_emblem",
        "tailgate_decal",
        "tailgate_handle",
        "tailgate_shock",
        "headlamp_foglamp_base",
    }:
        return True
    if requested_family in {"bumper_absorber", "bumper_support", "bumper_lamp", "bumper_cover"} and candidate_family in {
        "body_panel",
        "bumper_absorber",
        "bumper_support",
        "bumper_clip",
        "bumper_lamp",
        "bumper_cover",
    }:
        return True
    if requested_family in {"hood_hinge", "hood"} and candidate_family in {"body_panel", "hood_hinge", "hood"}:
        return True
    if requested_family in {"front_fender", "side_step_trim", "wheel_well_liner"} and candidate_family in {
        "body_panel",
        "front_fender",
        "side_step_trim",
        "wheel_well_liner",
    }:
        return True
    if requested_family == "headlamp_foglamp_base" and candidate_family in {"body_panel", "headlamp_foglamp_base", "headlamp_foglamp"}:
        return True
    if requested_family == "wiper_kit" and candidate_family in {"wiper_kit", "windshield_wiper_arm"}:
        return True
    if requested_family == "oil_filter" and candidate_family in {"oil_filter", "filter"}:
        return True
    if requested_family == "cabin_filter" and candidate_family in {"cabin_filter", "filter"}:
        return True
    if requested_family == "gasket" and candidate_family in {"gasket", "windshield_seal", "cylinder_head_gasket"}:
        return True
    if requested_family == "bearing" and candidate_family in {"bearing", "wheel_bearing"}:
        return True
    return False


def part_family_points(
    requested_family: str | None,
    candidate_family: str | None,
) -> int:
    if not requested_family or not candidate_family:
        return 0
    if requested_family == candidate_family:
        return 34 if requested_family not in GENERIC_PART_FAMILIES else 24
    if part_family_is_compatible(requested_family, candidate_family):
        return 18
    return 0


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

    if foreign_brand_detected:
        reasons.append(
            f"Provider item points to a different brand ({', '.join(sorted(item_brands))})."
        )
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
            "compatible": True,
        },
        reasons,
    )


def _extract_years(*values: Any) -> set[int]:
    years: set[int] = set()
    haystack = " ".join(str(value or "") for value in values)
    for start_text, end_text in YEAR_RANGE_PATTERN.findall(haystack):
        start = int(start_text)
        end = int(end_text)
        if end < start:
            start, end = end, start
        if end - start <= 15:
            years.update(range(start, end + 1))
    for year_text in YEAR_PATTERN.findall(haystack):
        years.add(int(year_text))
    return years


def _detect_token_group(text: str, groups: dict[str, frozenset[str]]) -> str | None:
    normalized = normalize_text(text)
    token_values = token_set(normalized)
    for label, group_tokens in groups.items():
        if token_values & group_tokens:
            return label
    return None


def compatibility_warnings(
    part_name: str,
    quote_context: dict[str, Any],
    item: ProviderItem,
    preferences: dict[str, Any],
) -> tuple[list[str], list[str]]:
    risk_flags: list[str] = []
    notes: list[str] = []
    item_text = " ".join(
        str(value or "")
        for value in (
            item.title,
            item.category_name,
            item.subcategory_name,
            item.reference,
            item.sku,
            item.supplier_item_code,
        )
    )

    requested_side = _detect_token_group(part_name, SIDE_TOKEN_GROUPS)
    candidate_side = _detect_token_group(item_text, SIDE_TOKEN_GROUPS)
    if requested_side and candidate_side and requested_side != candidate_side:
        risk_flags.append("side_mismatch")
        notes.append("lado distinto al solicitado")

    requested_position = _detect_token_group(part_name, POSITION_TOKEN_GROUPS)
    candidate_position = _detect_token_group(item_text, POSITION_TOKEN_GROUPS)
    if requested_position and candidate_position and requested_position != candidate_position:
        risk_flags.append("position_mismatch")
        notes.append("posicion distinta en el vehiculo")

    requested_presentation = _detect_token_group(part_name, PRESENTATION_TOKEN_GROUPS)
    candidate_presentation = _detect_token_group(item_text, PRESENTATION_TOKEN_GROUPS)
    if requested_presentation and candidate_presentation and requested_presentation != candidate_presentation:
        risk_flags.append("presentation_mismatch")
        notes.append("presentacion distinta entre kit y unidad")

    requested_color = _detect_token_group(part_name, COLOR_TOKEN_GROUPS)
    candidate_color = _detect_token_group(item_text, COLOR_TOKEN_GROUPS)
    if requested_color and candidate_color and requested_color != candidate_color:
        risk_flags.append("color_mismatch")
        notes.append("color visible distinto al solicitado")

    requested_finish = _detect_token_group(part_name, FINISH_TOKEN_GROUPS)
    candidate_finish = _detect_token_group(item_text, FINISH_TOKEN_GROUPS)
    if requested_finish and candidate_finish and requested_finish != candidate_finish:
        risk_flags.append("finish_mismatch")
        notes.append("acabado visible distinto al solicitado")

    quote_year = None
    try:
        quote_year = int(str(quote_context.get("ano") or "").strip())
    except ValueError:
        quote_year = None

    candidate_years = _extract_years(item_text)
    year_tolerance = int(preferences.get("year_tolerance") or 0)
    if quote_year and candidate_years:
        if not any(abs(year - quote_year) <= year_tolerance for year in candidate_years):
            risk_flags.append("year_mismatch")
            if len(candidate_years) <= 4:
                sorted_years = sorted(candidate_years)
                if len(sorted_years) > 1:
                    notes.append(f"ano fuera del rango visible {sorted_years[0]}-{sorted_years[-1]}")
                else:
                    notes.append(f"ano visible {sorted_years[0]} no coincide")
            else:
                notes.append("ano visible no coincide")

    return list(dict.fromkeys(risk_flags)), list(dict.fromkeys(notes))


def apply_preference_adjustments(
    item: ProviderItem,
    score: int,
    preferences: dict[str, Any],
) -> tuple[int, list[str]]:
    notes: list[str] = []
    adjusted = score
    provider_id = normalize_text(item.provider_id)
    item_brand = normalize_text(item.brand)

    if provider_id and provider_id in set(preferences.get("preferred_providers") or []):
        adjusted += 8
        notes.append(f"prioriza {provider_id} por preferencia del taller")
    if provider_id and provider_id in set(preferences.get("avoided_providers") or []):
        adjusted -= 20
        notes.append(f"penaliza {provider_id} por preferencia del taller")
    if item_brand and item_brand in set(preferences.get("preferred_brands") or []):
        adjusted += 5
        notes.append(f"marca {item.brand} preferida para este taller")
    if item_brand and item_brand in set(preferences.get("avoided_brands") or []):
        adjusted -= 12
        notes.append(f"marca {item.brand} marcada para evitar")

    return max(0, min(int(adjusted), 100)), notes


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
    return json.loads(path.read_text(encoding="utf-8-sig"))


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


def build_catalog_index(
    items: list[ProviderItem],
    provider_specs: dict[str, dict[str, Any]],
    *,
    source: str = "unknown",
    source_detail: str | None = None,
) -> CatalogIndex:
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
        source=source,
        source_detail=source_detail,
    )


def load_provider_catalog_index_from_database(database_url: str) -> CatalogIndex | None:
    try:
        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH latest_snapshots AS (
                      SELECT
                        pcs.*,
                        row_number() OVER (
                          PARTITION BY pcs.provider_id
                          ORDER BY pcs.snapshot_date DESC NULLS LAST, pcs.loaded_at DESC, pcs.id DESC
                        ) AS rn
                      FROM provider_catalog_snapshots pcs
                    )
                    SELECT
                      ls.id AS snapshot_id,
                      ls.provider_id,
                      ls.provider_name AS snapshot_provider_name,
                      ls.provider_type AS snapshot_provider_type,
                      ls.snapshot_date,
                      ls.source_path,
                      ls.provider_metadata,
                      ls.snapshot_metadata,
                      ls.notes AS snapshot_notes,
                      pp.title,
                      pp.normalized_title,
                      pp.category_name,
                      pp.subcategory_name,
                      pp.brand,
                      pp.reference,
                      pp.sku,
                      pp.supplier_item_code,
                      pp.detail_url,
                      pp.raw_match_type,
                      pp.requires_manual_confirmation,
                      pp.searchable_tokens,
                      pp.taxonomy_labels,
                      pp.notes AS product_notes
                    FROM latest_snapshots ls
                    JOIN provider_products pp ON pp.snapshot_id = ls.id
                    WHERE ls.rn = 1
                    ORDER BY ls.provider_id, pp.id
                    """
                )
                rows = cur.fetchall()
    except Exception:
        return None

    if not rows:
        return None

    items: list[ProviderItem] = []
    provider_specs: dict[str, dict[str, Any]] = {}

    for row in rows:
        provider_id = row["provider_id"]
        provider_metadata = row.get("provider_metadata") or {}
        snapshot_payload = {
            "notes": list(row.get("snapshot_notes") or []),
            "snapshot_date": row.get("snapshot_date"),
            "source_path": row.get("source_path"),
        }
        provider_specs.setdefault(
            provider_id,
            {
                "provider_id": provider_id,
                "display_name": row.get("snapshot_provider_name") or provider_metadata.get("display_name") or provider_id.title(),
                "website": provider_metadata.get("website"),
                "matching": provider_metadata.get("matching", {}),
                "data_precision": provider_metadata.get("data_precision", {}),
                "snapshot_date": row.get("snapshot_date"),
                "snapshot_path": row.get("source_path"),
                "notes": list(provider_item_notes(provider_id, provider_metadata, snapshot_payload)),
            },
        )
        items.append(
            ProviderItem(
                provider_id=provider_id,
                provider_name=row.get("snapshot_provider_name") or provider_metadata.get("display_name") or provider_id.title(),
                provider_type=row.get("snapshot_provider_type") or provider_metadata.get("provider_type") or "catalog",
                detail_url=row.get("detail_url"),
                title=row.get("title") or row.get("normalized_title") or "Unnamed product",
                category_name=row.get("category_name"),
                subcategory_name=row.get("subcategory_name"),
                brand=row.get("brand"),
                reference=row.get("reference"),
                sku=row.get("sku"),
                supplier_item_code=row.get("supplier_item_code"),
                taxonomy_labels=tuple(sorted(set(row.get("taxonomy_labels") or []))),
                searchable_tokens=frozenset(str(token) for token in (row.get("searchable_tokens") or []) if token),
                raw_match_type=row.get("raw_match_type"),
                requires_manual_confirmation=bool(row.get("requires_manual_confirmation")),
                notes=tuple(dict.fromkeys([*(str(value) for value in (row.get("product_notes") or [])), *provider_item_notes(provider_id, provider_metadata, snapshot_payload)])),
            )
        )

    return build_catalog_index(
        items,
        provider_specs,
        source="postgres",
        source_detail="provider_catalog_snapshots+provider_products",
    )


def load_provider_catalog_index_from_snapshots(providers_root: Path = DEFAULT_PROVIDERS_ROOT) -> CatalogIndex:
    items: list[ProviderItem] = []
    provider_specs: dict[str, dict[str, Any]] = {}

    if not providers_root.exists():
        return CatalogIndex(
            items=[],
            provider_specs={},
            references=defaultdict(set),
            tokens=defaultdict(set),
            taxonomies=defaultdict(set),
            source="snapshots",
            source_detail=str(providers_root),
        )

    def append_item(
        *,
        provider_id: str,
        metadata: dict[str, Any],
        snapshot: dict[str, Any],
        title: str | None,
        detail_url: str | None,
        category_name: str | None,
        subcategory_name: str | None,
        brand: str | None,
        reference: str | None,
        sku: str | None,
        supplier_item_code: str | None,
        searchable_tokens_value: Any,
        taxonomy_labels_value: tuple[str, ...],
        raw_match_type: str | None,
        requires_manual_confirmation: bool,
        notes_value: tuple[str, ...],
        provider_type: str | None = None,
        source_page_url: str | None = None,
    ) -> None:
        if not detail_url:
            return
        normalized_title = normalize_text(title or '')
        if normalized_title in {'previous slide', 'next slide', 'continuar comprando'}:
            return
        if not title:
            title = detail_url
        if provider_id == 'redpuestos' and normalize_text(title or '') == normalize_text('11400-718**, 435** (4.52) 21 calificaciones Stock: 5 🚘 Vehículos compatibles Entrega: desde el jueves 2 de julio. Agregar'):
            return
        if isinstance(searchable_tokens_value, list):
            tokens = frozenset(str(token) for token in searchable_tokens_value if token)
        else:
            tokens = filtered_token_set(
                ' '.join(
                    str(value or '')
                    for value in (
                        title,
                        category_name,
                        subcategory_name,
                        brand,
                        reference,
                        sku,
                        supplier_item_code,
                    )
                ),
                ignored_tokens=frozenset(),
            )
        effective_manual = requires_manual_confirmation
        if not effective_manual:
            match_confidence = normalize_text('')
            if isinstance(snapshot, dict):
                match_confidence = normalize_text(str(snapshot.get('match_confidence') or ''))
            if match_confidence in {'low', 'very low', 'manual', 'needs_manual_confirmation'}:
                effective_manual = True
        items.append(
            ProviderItem(
                provider_id=provider_id,
                provider_name=metadata.get('display_name', provider_id.title()),
                provider_type=provider_type or metadata.get('provider_type') or 'catalog',
                detail_url=detail_url,
                title=title,
                category_name=category_name,
                subcategory_name=subcategory_name,
                brand=brand,
                reference=reference,
                sku=sku,
                supplier_item_code=supplier_item_code,
                taxonomy_labels=taxonomy_labels_value,
                searchable_tokens=tokens,
                raw_match_type=raw_match_type,
                requires_manual_confirmation=effective_manual,
                notes=tuple(dict.fromkeys([*(str(value) for value in notes_value if value), *provider_item_notes(provider_id, metadata, snapshot)])),
            )
        )

    for provider_dir in sorted(providers_root.iterdir()):
        if not provider_dir.is_dir():
            continue
        provider_id = provider_dir.name
        start_len = len(items)
        metadata_path = provider_dir / 'provider.json'
        snapshot_path = latest_snapshot_json(provider_dir)
        if not metadata_path.exists() or snapshot_path is None:
            continue
        metadata = load_json(metadata_path)
        snapshot = load_json(snapshot_path)
        products = snapshot.get('products') or []
        service_families = snapshot.get('service_families') or []
        service_series = snapshot.get('service_series') or []
        provider_specs[provider_id] = {
            'provider_id': provider_id,
            'display_name': metadata.get('display_name', provider_id.title()),
            'website': metadata.get('website'),
            'matching': metadata.get('matching', {}),
            'data_precision': metadata.get('data_precision', {}),
            'snapshot_date': snapshot.get('snapshot_date'),
            'snapshot_path': str(snapshot_path),
            'notes': list(provider_item_notes(provider_id, metadata, snapshot)),
        }

        if isinstance(products, list) and products:
            for product in products:
                if not isinstance(product, dict):
                    continue
                detail_url = (
                    product.get('detail_url')
                    or product.get('product_url')
                    or product.get('source_page_url')
                )
                append_item(
                    provider_id=provider_id,
                    metadata=metadata,
                    snapshot=snapshot,
                    title=product.get('title') or product.get('product_name') or product.get('description') or 'Unnamed product',
                    detail_url=detail_url,
                    category_name=product.get('category_name'),
                    subcategory_name=product.get('subcategory_name'),
                    brand=product.get('brand'),
                    reference=product.get('reference'),
                    sku=product.get('sku'),
                    supplier_item_code=product.get('supplier_item_code'),
                    searchable_tokens_value=product.get('searchable_tokens'),
                    taxonomy_labels_value=tuple(
                        label
                        for label in dict.fromkeys(
                            [
                                str(product.get('category_name') or '').strip(),
                                str(product.get('subcategory_name') or '').strip(),
                                str(product.get('vehicle_scope') or '').strip(),
                            ]
                        )
                        if label
                    ),
                    raw_match_type=product.get('raw_match_type') or product.get('match_type'),
                    requires_manual_confirmation=bool(product.get('requires_manual_confirmation')),
                    notes_value=tuple(str(value) for value in (product.get('notes') or []) if value),
                    provider_type=product.get('provider_type') or metadata.get('provider_type') or 'catalog',
                    source_page_url=product.get('source_page_url'),
                )
            continue

        if provider_id == 'disfal':
            for family in service_families:
                if not isinstance(family, dict):
                    continue
                append_item(
                    provider_id=provider_id,
                    metadata=metadata,
                    snapshot=snapshot,
                    title=family.get('family_name') or family.get('taxonomy_label') or 'Disfal family',
                    detail_url=family.get('family_url'),
                    category_name=family.get('taxonomy_label'),
                    subcategory_name=family.get('family_slug'),
                    brand=None,
                    reference=None,
                    sku=None,
                    supplier_item_code=None,
                    searchable_tokens_value=family.get('family_name'),
                    taxonomy_labels_value=tuple(
                        label
                        for label in dict.fromkeys(
                            [
                                str(family.get('taxonomy_label') or '').strip(),
                                str(family.get('family_name') or '').strip(),
                            ]
                        )
                        if label
                    ),
                    raw_match_type=family.get('match_type') or 'category_only',
                    requires_manual_confirmation=bool(family.get('requires_manual_confirmation')),
                    notes_value=tuple(str(value) for value in (family.get('notes') or []) if value),
                    provider_type=metadata.get('provider_type') or 'service_catalog',
                    source_page_url=family.get('source_page_url'),
                )
            for series in service_series:
                if not isinstance(series, dict):
                    continue
                append_item(
                    provider_id=provider_id,
                    metadata=metadata,
                    snapshot=snapshot,
                    title=series.get('series_label') or series.get('service_name') or 'Disfal series',
                    detail_url=series.get('service_url'),
                    category_name=series.get('service_name'),
                    subcategory_name=series.get('series_label'),
                    brand=series.get('brand_name'),
                    reference=None,
                    sku=None,
                    supplier_item_code=None,
                    searchable_tokens_value=' '.join(
                        str(value or '')
                        for value in (
                            series.get('series_label'),
                            series.get('service_name'),
                            series.get('brand_name'),
                            series.get('commercial_line'),
                        )
                    ),
                    taxonomy_labels_value=tuple(
                        label
                        for label in dict.fromkeys(
                            [
                                str(series.get('taxonomy_label') or '').strip(),
                                str(series.get('service_name') or '').strip(),
                                str(series.get('series_label') or '').strip(),
                            ]
                        )
                        if label
                    ),
                    raw_match_type=series.get('match_type') or 'category_only',
                    requires_manual_confirmation=bool(series.get('requires_manual_confirmation')),
                    notes_value=tuple(str(value) for value in (series.get('verification_note') or series.get('notes') or []) if value),
                    provider_type=metadata.get('provider_type') or 'service_catalog',
                    source_page_url=series.get('source_page_url'),
                )

        if len(items) == start_len:
            provider_specs.pop(provider_id, None)

    return build_catalog_index(
        items,
        provider_specs,
        source="snapshots",
        source_detail=str(providers_root),
    )

def load_provider_catalog_index(
    providers_root: Path = DEFAULT_PROVIDERS_ROOT,
    *,
    catalog_source: str | None = None,
) -> CatalogIndex:
    source_mode = normalize_text(
        catalog_source or os.environ.get("ORBIKA_PROVIDER_CATALOG_SOURCE") or "db-first"
    )
    database_url = resolve_provider_catalog_database_url()

    if source_mode in {"db", "postgres", "postgresql"}:
        if not database_url:
            raise RuntimeError(
                "Se solicito catalog_source=db pero DATABASE_URL no esta configurado."
            )
        db_index = load_provider_catalog_index_from_database(database_url)
        if db_index is None or not db_index.items:
            raise RuntimeError(
                "Se solicito catalog_source=db pero no fue posible cargar el catalogo desde PostgreSQL."
            )
        return db_index

    if source_mode in {"snapshots", "filesystem", "local"}:
        return load_provider_catalog_index_from_snapshots(providers_root)

    if database_url:
        db_index = load_provider_catalog_index_from_database(database_url)
        if db_index is not None and db_index.items:
            return db_index

    return load_provider_catalog_index_from_snapshots(providers_root)

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

    content_candidate_ids: set[int] = set()
    for taxonomy in requested_taxonomies:
        content_candidate_ids.update(index.taxonomies.get(taxonomy, set()))
    search_tokens = set(part_tokens)
    if "kit" in search_tokens and len(search_tokens) > 1:
        search_tokens.discard("kit")
    for token in search_tokens:
        content_candidate_ids.update(index.tokens.get(token, set()))

    candidate_ids.update(content_candidate_ids)
    if candidate_ids:
        return candidate_ids

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
    if taxonomy_overlap and score >= 50:
        return "category_only"
    if requested_reference and score >= 50:
        return "manual_confirmation_required"
    return "manual_confirmation_required"


def score_item(
    part_name: str,
    requested_reference: str | None,
    part_tokens: frozenset[str],
    quote_context: dict[str, Any],
    quote_vehicle: VehicleProfile,
    requested_taxonomies: tuple[str, ...],
    item: ProviderItem,
    preferences: dict[str, Any],
) -> tuple[int, list[str], str, list[str], list[str]]:
    reasons: list[str] = []
    preference_notes: list[str] = []
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
    query_family = infer_part_family(part_name)
    item_family = infer_part_family(
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
    item_brands = item_brand_tokens(item)
    family_points = part_family_points(query_family, item_family)
    reference_text_hit = bool(
        requested_reference
        and (
            requested_reference in normalized_item_refs
            or requested_reference in item.searchable_tokens
        )
    )
    compatibility, compatibility_reasons = vehicle_compatibility(quote_vehicle, item)
    risk_flags, compatibility_notes = compatibility_warnings(
        part_name,
        quote_context,
        item,
        preferences,
    )
    reasons.extend(compatibility_reasons)

    if requested_reference is None and title_similarity < 0.32 and token_overlap_value <= 0:
        reasons.append("Candidate name is too far from the requested part name.")
        return 0, reasons, "manual_confirmation_required", risk_flags, preference_notes

    if query_family and item_family and not part_family_is_compatible(query_family, item_family):
        reasons.append(
            f"Candidate part family ({item_family}) does not match the requested family ({query_family})."
        )
        return 0, reasons, "manual_confirmation_required", risk_flags, preference_notes

    if (
        query_family
        and not item_family
        and query_family not in GENERIC_PART_FAMILIES
        and title_similarity < 0.55
        and token_overlap_value < 0.28
    ):
        reasons.append("Candidate does not expose enough evidence for the requested specific part family.")
        return 0, reasons, "manual_confirmation_required", risk_flags, preference_notes

    if (
        not reference_text_hit
        and family_points <= 0
        and not item_family
        and title_similarity < 0.24
        and token_overlap_value < 0.12
    ):
        reasons.append("Candidate keeps only weak contextual overlap and does not match the requested part name.")
        return 0, reasons, "manual_confirmation_required", risk_flags, preference_notes

    if quote_vehicle.brand_tokens:
        if item_brands and compatibility["foreign_brand_detected"]:
            if query_family in BRAND_FLEXIBLE_FAMILIES:
                reasons.append(
                    "Provider item points to a different vehicle brand, so it can only remain as a weak/manual candidate."
                )
            else:
                reasons.append("Provider item brand conflicts with the requested vehicle brand for this part family.")
                return 0, reasons, "manual_confirmation_required", risk_flags, preference_notes
        if (
            not item_brands
            and compatibility["brand_overlap"] <= 0
            and title_similarity < 0.45
            and query_family not in BRAND_FLEXIBLE_FAMILIES
        ):
            reasons.append("Missing brand evidence keeps this candidate too weak.")
            return 0, reasons, "manual_confirmation_required", risk_flags, preference_notes

    score = 0
    if requested_reference and requested_reference in normalized_item_refs:
        exact_reference_hit = True
        score = 100
        reasons.append(f"Exact reference match: {requested_reference}")
    elif requested_reference and requested_reference in item.searchable_tokens:
        score = 95
        reasons.append(f"Reference token was found in provider text: {requested_reference}")
    else:
        if query_signal and item_signal and item_signal not in PART_SIGNAL_COMPATIBILITY.get(query_signal, {query_signal}):
            reasons.append(
                f"Candidate part type ({item_signal}) does not match the requested part type ({query_signal})."
            )
            return 0, reasons, "manual_confirmation_required", risk_flags, preference_notes
        signal_points = part_signal_points(query_signal, item_signal)
        if (
            part_tokens
            and not part_overlap_tokens
            and item.provider_type != "category_only"
            and family_points <= 0
            and signal_points <= 0
        ):
            reasons.append("Candidate does not share any relevant part-name tokens.")
            return 0, reasons, "manual_confirmation_required", risk_flags, preference_notes
        if taxonomy_overlap:
            score += 22
            reasons.append("Taxonomy/family looks compatible.")
        if family_points > 0:
            score += family_points
            reasons.append(f"Part-family compatibility contributes {family_points} points.")
        if signal_points > 0:
            score += signal_points
            reasons.append(f"Part-type compatibility contributes {signal_points} points.")
        if token_overlap_value > 0:
            token_points = round(token_overlap_value * (38 if family_points > 0 else 30))
            score += token_points
            reasons.append(f"Part-name token overlap contributes {token_points} points.")
        if title_similarity >= 0.25:
            name_multiplier = 24 if query_family else 20
            name_points = round(title_similarity * name_multiplier)
            score += name_points
            reasons.append(f"Product-name similarity contributes {name_points} points.")
        if compatibility["brand_overlap"] > 0:
            brand_points = min(compatibility["brand_overlap"] * 18, 30)
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

    if query_family and query_family not in GENERIC_PART_FAMILIES and not exact_reference_hit:
        if family_points > 0 and token_overlap_value < 0.18 and title_similarity < 0.5:
            score = min(score, 42)
            reasons.append(
                "Specific family match stays weak because the candidate name has little direct overlap."
            )
        elif family_points <= 0 and taxonomy_overlap and token_overlap_value < 0.15:
            score = min(score, 32)
            reasons.append(
                "Taxonomy overlap alone is not enough for this specific part family."
            )

    if query_family and query_family not in GENERIC_PART_FAMILIES and family_points <= 0 and not exact_reference_hit:
        score = min(score, 45)
        reasons.append("Specific part family could not be confirmed explicitly in provider text.")

    if compatibility["foreign_brand_detected"]:
        if query_family in BRAND_FLEXIBLE_FAMILIES:
            score = min(score, 35)
            reasons.append("Brand mismatch keeps this candidate in manual validation.")
        else:
            return 0, reasons, "manual_confirmation_required", risk_flags, preference_notes

    if any(flag in HARD_CONFLICT_RISK_FLAGS for flag in risk_flags):
        reasons.extend(f"Compatibility warning: {note}." for note in compatibility_notes)
        return 0, reasons, "manual_confirmation_required", risk_flags, preference_notes
    for flag, cap in SOFT_WARNING_SCORE_CAPS.items():
        if flag in risk_flags:
            reasons.extend(f"Compatibility warning: {note}." for note in compatibility_notes)
            score = min(score, cap)

    score, preference_notes = apply_preference_adjustments(item, score, preferences)
    if preferences.get("prefer_exact_reference") and requested_reference and not exact_reference_hit:
        score = min(score, 72)
        preference_notes.append("se prioriza referencia exacta cuando exista")

    if item.raw_match_type == "web_validated" and score > 0:
        if part_overlap_tokens and compatibility["brand_overlap"] > 0 and compatibility["line_overlap"] > 0:
            score = max(score, 92)
            reasons.append("Web-validated provider product matches requested part, brand and line.")
        elif part_overlap_tokens and compatibility["brand_overlap"] > 0:
            score = max(score, 82)
            reasons.append("Web-validated provider product matches requested part and brand.")

    if item.provider_id in {"impocali", "disfal"}:
        score = min(score, 55 if taxonomy_overlap else 25)
    elif item.provider_id == "partcar":
        score = min(score, 78 if taxonomy_overlap else 60)
    elif not exact_reference_hit and requested_reference is None and item.raw_match_type != "web_validated":
        score = min(score, 88)

    if score < 20:
        return 0, reasons, "manual_confirmation_required", risk_flags, preference_notes

    if item.raw_match_type == "web_validated" and score >= 70:
        match_type = "web_validated"
    else:
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
    return max(0, min(score, 100)), reasons, match_type, risk_flags, preference_notes


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


def compatibility_state_for_match(entry: dict[str, Any]) -> str:
    risk_flags = set(entry.get("risk_flags") or [])
    if risk_flags & HARD_CONFLICT_RISK_FLAGS:
        return "incompatible"
    if risk_flags:
        return "warning"
    if entry.get("provider_id") in {"impocali", "disfal"}:
        return "insufficient_information"
    if entry.get("requires_manual_confirmation"):
        return "insufficient_information"
    return "compatible"


def compatibility_summary_for_match(entry: dict[str, Any]) -> str:
    warnings = list(entry.get("compatibility_warnings") or [])
    if warnings:
        return warnings[0]
    preference_notes = list(entry.get("preference_notes") or [])
    if entry.get("match_type") == "exact_reference":
        return "referencia exacta visible"
    if entry.get("provider_id") in {"impocali", "disfal"}:
        return "coincidencia por familia o categoria; validar manualmente"
    if preference_notes:
        return preference_notes[0]
    if entry.get("requires_manual_confirmation"):
        return "informacion insuficiente; requiere validacion manual"
    if entry.get("match_type") == "vehicle_compatible":
        return "compatible por vehiculo y tipo de repuesto"
    return "coincidencia parcial sin alertas visibles"


def build_match_entry(
    part_name: str,
    item: ProviderItem,
    score: int,
    match_type: str,
    reasons: list[str],
    risk_flags: list[str],
    preference_notes: list[str],
) -> dict[str, Any]:
    compatibility_warnings = [
        flag.replace("_", " ")
        for flag in risk_flags
    ]
    requested_part_family = infer_part_family(part_name)
    candidate_part_family = infer_part_family(
        item.title,
        item.category_name,
        item.subcategory_name,
        " ".join(item.taxonomy_labels),
    )
    entry = {
        "provider_id": item.provider_id,
        "provider_name": item.provider_name,
        "product_name": item.title,
        "score_percent": score,
        "match_type": match_type,
        "detail_url": item.detail_url,
        "part_name": part_name,
        "requested_part_family": requested_part_family,
        "candidate_part_family": candidate_part_family,
        "reference": item.reference,
        "sku": item.sku,
        "supplier_item_code": item.supplier_item_code,
        "brand": item.brand,
        "category_name": item.category_name,
        "subcategory_name": item.subcategory_name,
        "taxonomy_labels": list(item.taxonomy_labels),
        "requires_manual_confirmation": item.requires_manual_confirmation or match_type not in {"exact_reference", "web_validated"},
        "summary": summarize_match(item, score, match_type),
        "notes": list(item.notes),
        "reasons": reasons,
        "risk_flags": risk_flags,
        "compatibility_warnings": compatibility_warnings,
        "preference_notes": preference_notes,
    }
    entry["compatibility_state"] = compatibility_state_for_match(entry)
    entry["compatibility_summary"] = compatibility_summary_for_match(entry)
    entry["operational_note"] = entry["compatibility_summary"] or summarize_match(item, score, match_type)
    return entry


def dedupe_match_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for entry in entries:
        dedupe_key = (
            str(entry.get("provider_id") or ""),
            normalize_text(entry.get("part_name")),
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
    preferences: dict[str, Any],
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
        score, reasons, match_type, risk_flags, preference_notes = score_item(
            part_name=part_name,
            requested_reference=requested_reference,
            part_tokens=part_tokens,
            quote_context=quote_context,
            quote_vehicle=quote_vehicle,
            requested_taxonomies=requested_taxonomies,
            item=item,
            preferences=preferences,
        )
        if score <= 0:
            continue
        scored_matches.append(
            build_match_entry(part_name, item, score, match_type, reasons, risk_flags, preference_notes)
        )

    scored_matches.sort(
        key=lambda entry: (
            entry["score_percent"],
            1 if entry["match_type"] in {"exact_reference", "web_validated"} else 0,
            entry["provider_name"],
            entry["part_name"],
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




def build_provider_review(index: CatalogIndex) -> dict[str, Any]:
    grouped: dict[str, list[ProviderItem]] = defaultdict(list)
    for item in index.items:
        grouped[item.provider_id].append(item)

    providers: list[dict[str, Any]] = []
    for provider_id in sorted(grouped):
        items = grouped[provider_id]
        spec = index.provider_specs.get(provider_id, {})
        provider_types: dict[str, int] = defaultdict(int)
        match_types: dict[str, int] = defaultdict(int)
        taxonomy_labels: dict[str, int] = defaultdict(int)
        payload_items: list[dict[str, Any]] = []

        for item in items:
            provider_types[item.provider_type] += 1
            if item.raw_match_type:
                match_types[item.raw_match_type] += 1
            for label in item.taxonomy_labels:
                taxonomy_labels[label] += 1
            payload_items.append(
                {
                    "provider_type": item.provider_type,
                    "title": item.title,
                    "detail_url": item.detail_url,
                    "category_name": item.category_name,
                    "subcategory_name": item.subcategory_name,
                    "brand": item.brand,
                    "reference": item.reference,
                    "sku": item.sku,
                    "supplier_item_code": item.supplier_item_code,
                    "taxonomy_labels": list(item.taxonomy_labels),
                    "match_type": item.raw_match_type,
                    "requires_manual_confirmation": item.requires_manual_confirmation,
                    "notes": list(item.notes[:2]),
                }
            )

        providers.append(
            {
                "provider_id": provider_id,
                "provider_name": spec.get("display_name") or items[0].provider_name,
                "snapshot_date": spec.get("snapshot_date"),
                "snapshot_path": spec.get("snapshot_path"),
                "website": spec.get("website"),
                "notes": list(spec.get("notes") or []),
                "item_count": len(items),
                "provider_types": dict(sorted(provider_types.items())),
                "match_types": dict(sorted(match_types.items())),
                "taxonomy_labels": dict(sorted(taxonomy_labels.items(), key=lambda pair: (-pair[1], pair[0]))),
                "items": payload_items,
            }
        )

    return {
        "generated_at": utc_now(),
        "provider_count": len(providers),
        "providers": providers,
    }


def write_provider_review_reports(daily_dir: Path, index: CatalogIndex) -> tuple[Path, Path]:
    review = build_provider_review(index)
    json_path = daily_dir / "provider-review.json"
    md_path = daily_dir / "provider-review.md"
    json_path.write_text(json.dumps(review, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    md_lines = [
        f"# Provider Review {date}",
        "",
        f"- Providers: {review['provider_count']}",
        f"- Total items: {sum(provider['item_count'] for provider in review['providers'])}",
        "",
    ]
    for provider in review["providers"]:
        md_lines.extend(
            [
                f"## {provider['provider_name']}",
                "",
                f"- Provider ID: `{provider['provider_id']}`",
                f"- Snapshot date: `{provider['snapshot_date'] or 'n/a'}`",
                f"- Items: {provider['item_count']}",
                f"- Provider types: {json.dumps(provider['provider_types'], ensure_ascii=False)}",
                f"- Match types: {json.dumps(provider['match_types'], ensure_ascii=False)}",
                f"- Taxonomy labels: {json.dumps(provider['taxonomy_labels'], ensure_ascii=False)}",
                "",
            ]
        )
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    return json_path, md_path

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
    preferences = load_customer_preferences_for_quote(quote_payload)
    effective_limit = min(limit_per_part, int(preferences.get("max_options_per_part") or limit_per_part))
    part_reports = [
        match_quote_part(part, quote_context, index, preferences=preferences, limit=effective_limit)
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
        "catalog": {
            "source": index.source,
            "source_detail": index.source_detail,
        },
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
        "preferences": {
            "applied_scopes": preferences.get("applied_scopes", []),
            "applied_preferences": preferences.get("applied_preferences", []),
            "prefer_exact_reference": preferences.get("prefer_exact_reference", False),
            "year_tolerance": preferences.get("year_tolerance", 0),
        },
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
    path.write_text(json.dumps(compact_payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


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
        json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

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
    catalog_source: str | None = None,
) -> dict[str, Any]:
    index = load_provider_catalog_index(providers_root, catalog_source=catalog_source)
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
    parser.add_argument(
        "--catalog-source",
        choices=("db-first", "db", "snapshots"),
        default="db-first",
        help="Source policy for provider catalogs. Default: db-first.",
    )
    return parser.parse_args(argv)

def main(argv: list[str]) -> int:
    args = parse_args(argv)
    result = enrich_quotes_dir(
        quotes_dir=args.quotes_dir,
        providers_root=args.providers_root,
        daily_dir=args.daily_report_dir,
        limit_per_part=args.limit_per_part,
        catalog_source=args.catalog_source,
    )
    print(
        "Supplier matching completed: "
        f"{result['quotes_enriched']} quote file(s) enriched. "
        f"Daily reports: {len(result['daily_reports_written'])}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))




