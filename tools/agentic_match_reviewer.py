#!/usr/bin/env python3
"""Optional agentic review layer on top of supplier_matching."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, TypedDict

from tools.supplier_quote_matcher import (
    DEFAULT_QUOTES_DIR,
    PART_SIGNAL_COMPATIBILITY,
    infer_primary_part_signal,
    load_json,
    normalize_reference,
    normalize_text,
    token_set,
    utc_now,
    vehicle_profile_from_quote_context,
    write_quote_payload,
)

try:
    from langgraph.graph import END, StateGraph

    LANGGRAPH_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    END = "__end__"
    StateGraph = None
    LANGGRAPH_AVAILABLE = False

try:
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_openai import ChatOpenAI

    LANGCHAIN_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    ChatPromptTemplate = None
    ChatOpenAI = None
    LANGCHAIN_AVAILABLE = False


DEFAULT_TRACE_DIR = Path("local/orbika_incremental/agentic_traces")


class PartReviewState(TypedDict, total=False):
    quote_context: dict[str, Any]
    part: dict[str, Any]
    candidates: list[dict[str, Any]]
    prepared_candidates: list[dict[str, Any]]
    selected_matches: list[dict[str, Any]]
    reviewer_mode: str
    trace: list[dict[str, Any]]
    notes: list[str]


class MatchReviewer(Protocol):
    def review(
        self,
        *,
        quote_context: dict[str, Any],
        part: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[str], str]:
        """Return selected matches, notes and reviewer mode."""


@dataclass
class HeuristicMatchReviewer:
    limit_per_part: int = 5

    def review(
        self,
        *,
        quote_context: dict[str, Any],
        part: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[str], str]:
        reviewed: list[dict[str, Any]] = []
        notes: list[str] = []
        vehicle = vehicle_profile_from_quote_context(quote_context)
        requested_signal = infer_primary_part_signal(
            part.get("part_name"),
            part.get("requested_reference"),
        )
        requested_tokens = token_set(
            part.get("part_name"),
            part.get("requested_reference"),
        )

        for candidate in candidates:
            reviewed_candidate = dict(candidate)
            adjusted_score = int(candidate.get("score_percent", 0))
            rationale = list(candidate.get("reasons", []))
            candidate_text = " ".join(
                str(value or "")
                for value in (
                    candidate.get("product_name"),
                    candidate.get("brand"),
                    candidate.get("category_name"),
                    candidate.get("subcategory_name"),
                    candidate.get("reference"),
                    candidate.get("sku"),
                )
            )
            candidate_tokens = token_set(candidate_text)
            candidate_signal = infer_primary_part_signal(
                candidate.get("product_name"),
                candidate.get("category_name"),
                candidate.get("subcategory_name"),
                candidate.get("reference"),
            )

            if requested_signal and candidate_signal:
                compatible_signals = PART_SIGNAL_COMPATIBILITY.get(
                    requested_signal,
                    {requested_signal},
                )
                if candidate_signal not in compatible_signals:
                    adjusted_score = 0
                    rationale.append(
                        f"Agentic review rejected part-type mismatch: {requested_signal} vs {candidate_signal}."
                    )
                elif candidate_signal == requested_signal:
                    adjusted_score += 8
                    rationale.append("Agentic review rewarded exact part-type alignment.")
                else:
                    adjusted_score += 4
                    rationale.append("Agentic review rewarded compatible part-type alignment.")

            brand_overlap = len(vehicle.brand_tokens & candidate_tokens)
            line_overlap = len(vehicle.line_tokens & candidate_tokens)
            version_overlap = len(vehicle.version_tokens & candidate_tokens)
            lexical_overlap = len(requested_tokens & candidate_tokens)

            if brand_overlap > 0:
                adjusted_score += min(brand_overlap * 8, 16)
                rationale.append("Agentic review rewarded vehicle brand alignment.")
            if line_overlap > 0:
                adjusted_score += min(line_overlap * 7, 14)
                rationale.append("Agentic review rewarded vehicle line alignment.")
            if version_overlap > 0:
                adjusted_score += min(version_overlap * 4, 8)
                rationale.append("Agentic review rewarded vehicle version alignment.")
            if lexical_overlap == 0 and candidate.get("provider_id") not in {"impocali", "disfal"}:
                adjusted_score -= 12
                rationale.append("Agentic review penalized low lexical overlap with the requested part.")

            if requested_signal == "wiper_kit" and "kit" not in normalize_text(candidate.get("product_name")):
                adjusted_score -= 18
                rationale.append("Agentic review penalized a non-kit result for a kit request.")

            reviewed_candidate["agentic_adjusted_score"] = max(0, min(int(adjusted_score), 100))
            reviewed_candidate["agentic_reasons"] = rationale
            reviewed.append(reviewed_candidate)

        reviewed.sort(
            key=lambda entry: (
                entry.get("agentic_adjusted_score", 0),
                1 if entry.get("match_type") == "exact_reference" else 0,
                entry.get("provider_name", ""),
                entry.get("product_name", ""),
            ),
            reverse=True,
        )

        selected = dedupe_agentic_matches(reviewed, limit=min(self.limit_per_part, 3))
        if selected:
            notes.append(
                "Agentic review reranked supplier candidates using stricter vehicle and part-type checks."
            )
        else:
            notes.append("Agentic review did not keep any candidate above the acceptance threshold.")
        return selected, notes, "heuristic_fallback"


@dataclass
class LLMMatchReviewer:
    llm: Any
    limit_per_part: int = 5

    def review(
        self,
        *,
        quote_context: dict[str, Any],
        part: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[str], str]:
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "You are reviewing supplier matches for an automotive quote. "
                        "Prioritize exact part type, vehicle brand, vehicle line and version. "
                        "Do not invent products. Return JSON only."
                    ),
                ),
                (
                    "human",
                    json.dumps(
                        {
                            "vehicle": quote_context,
                            "part": part,
                            "candidates": candidates[: self.limit_per_part + 5],
                            "instructions": {
                                "max_selected": self.limit_per_part,
                                "preserve_exact_reference_matches": True,
                                "avoid_wrong_part_type": True,
                                "avoid_wrong_vehicle_brand_or_line": True,
                            },
                        },
                        ensure_ascii=False,
                    ),
                ),
            ]
        )
        raw_response = self.llm.invoke(prompt.format_messages())
        content = getattr(raw_response, "content", raw_response)
        payload = json.loads(str(content))
        selected_indexes = payload.get("selected_indexes", [])
        selected: list[dict[str, Any]] = []
        for index in selected_indexes[: self.limit_per_part]:
            if isinstance(index, int) and 0 <= index < len(candidates):
                selected.append(dict(candidates[index]))
        return (
            dedupe_agentic_matches(selected, limit=min(self.limit_per_part, 3)),
            list(payload.get("notes", [])),
            "llm_review",
        )


def build_trace_event(stage: str, message: str, **details: Any) -> dict[str, Any]:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "message": message,
        "details": details,
    }


def dedupe_agentic_matches(entries: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    provider_seen: set[str] = set()
    for entry in entries:
        adjusted_score = int(entry.get("agentic_adjusted_score", entry.get("score_percent", 0)))
        minimum_score = 18 if entry.get("provider_id") in {"impocali", "disfal"} else 35
        if adjusted_score < minimum_score:
            continue
        provider_id = str(entry.get("provider_id") or "")
        if provider_id in provider_seen:
            continue
        dedupe_key = (
            provider_id,
            normalize_text(entry.get("product_name")),
            normalize_reference(entry.get("reference")) or "",
            normalize_reference(entry.get("sku")) or "",
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        provider_seen.add(provider_id)
        deduped.append(entry)
        if len(deduped) >= limit:
            break
    return deduped


def summarize_agentic_choice(entry: dict[str, Any], rank: int) -> str:
    provider_name = str(entry.get("provider_name") or "Proveedor")
    match_type = str(entry.get("match_type") or "")
    product_name = str(entry.get("product_name") or "").strip()
    if match_type == "exact_reference":
        return f"{provider_name}: referencia exacta."
    if rank == 1:
        return f"{provider_name}: mejor opcion."
    if entry.get("provider_id") in {"impocali", "disfal"}:
        return f"{provider_name}: validar manual."
    if "kit" in normalize_text(product_name):
        return f"{provider_name}: alternativa kit."
    return f"{provider_name}: alternativa."


def compact_agentic_match(entry: dict[str, Any], rank: int) -> dict[str, Any]:
    adjusted_score = int(entry.get("agentic_adjusted_score", entry.get("score_percent", 0)))
    return {
        "rank": rank,
        "provider_id": entry.get("provider_id"),
        "provider_name": entry.get("provider_name"),
        "score_percent": adjusted_score,
        "match_type": entry.get("match_type"),
        "product_name": entry.get("product_name"),
        "detail_url": entry.get("detail_url"),
        "reference": entry.get("reference"),
        "sku": entry.get("sku"),
        "brand": entry.get("brand"),
        "category_name": entry.get("category_name"),
        "subcategory_name": entry.get("subcategory_name"),
        "requires_manual_confirmation": bool(entry.get("requires_manual_confirmation")),
        "agentic_comment": summarize_agentic_choice(entry, rank),
    }


def choose_reviewer(limit_per_part: int, model_name: str | None = None) -> MatchReviewer:
    if (
        LANGCHAIN_AVAILABLE
        and ChatOpenAI is not None
        and os.getenv("OPENAI_API_KEY")
        and model_name
    ):
        llm = ChatOpenAI(model=model_name, temperature=0)
        return LLMMatchReviewer(llm=llm, limit_per_part=limit_per_part)
    return HeuristicMatchReviewer(limit_per_part=limit_per_part)


def prepare_candidates_node(state: PartReviewState) -> PartReviewState:
    trace = list(state.get("trace", []))
    candidates = [dict(candidate) for candidate in state.get("candidates", [])]
    trace.append(
        build_trace_event(
            "prepare_candidates",
            "Loaded candidates for agentic review.",
            candidates=len(candidates),
        )
    )
    state["prepared_candidates"] = candidates
    state["trace"] = trace
    return state


def review_candidates_node(state: PartReviewState, reviewer: MatchReviewer) -> PartReviewState:
    trace = list(state.get("trace", []))
    selected, notes, reviewer_mode = reviewer.review(
        quote_context=state["quote_context"],
        part=state["part"],
        candidates=state.get("prepared_candidates", []),
    )
    trace.append(
        build_trace_event(
            "review_candidates",
            "Reviewed candidate list.",
            candidates=len(state.get("prepared_candidates", [])),
            selected=len(selected),
            reviewer_mode=reviewer_mode,
        )
    )
    state["selected_matches"] = selected
    state["reviewer_mode"] = reviewer_mode
    state["notes"] = notes
    state["trace"] = trace
    return state


def finalize_part_review(state: PartReviewState) -> dict[str, Any]:
    selected = state.get("selected_matches", [])
    top_match = selected[0] if selected else None
    compact_selected = [
        compact_agentic_match(entry, rank=index + 1)
        for index, entry in enumerate(selected[:3])
    ]
    return {
        "part_name": state["part"].get("part_name"),
        "requested_reference": state["part"].get("requested_reference"),
        "review_status": "reviewed" if selected else "no_agentic_selection",
        "reviewer_mode": state.get("reviewer_mode", "heuristic_fallback"),
        "selected_count": len(compact_selected),
        "top_provider_id": top_match.get("provider_id") if top_match else None,
        "top_score_percent": top_match.get("agentic_adjusted_score", top_match.get("score_percent", 0))
        if top_match
        else 0,
        "selected_matches": compact_selected,
        "notes": state.get("notes", [])[:1],
        "trace": state.get("trace", []),
    }


def run_part_review(
    *,
    quote_context: dict[str, Any],
    part: dict[str, Any],
    reviewer: MatchReviewer,
) -> dict[str, Any]:
    initial_state: PartReviewState = {
        "quote_context": quote_context,
        "part": part,
        "candidates": list(part.get("matches", [])),
        "trace": [],
    }
    if LANGGRAPH_AVAILABLE and StateGraph is not None:
        graph = StateGraph(PartReviewState)
        graph.add_node("prepare_candidates", prepare_candidates_node)
        graph.add_node("review_candidates", lambda state: review_candidates_node(state, reviewer))
        graph.set_entry_point("prepare_candidates")
        graph.add_edge("prepare_candidates", "review_candidates")
        graph.add_edge("review_candidates", END)
        app = graph.compile()
        final_state = app.invoke(initial_state)
    else:
        final_state = review_candidates_node(prepare_candidates_node(initial_state), reviewer)
    return finalize_part_review(final_state)


def build_agentic_match_report(
    quote_payload: dict[str, Any],
    *,
    limit_per_part: int = 5,
    model_name: str | None = None,
) -> dict[str, Any]:
    supplier_matching = quote_payload.get("supplier_matching") or {}
    reviewer = choose_reviewer(limit_per_part=limit_per_part, model_name=model_name)
    quote_context = {
        "marca": quote_payload.get("orbika", {}).get("marca"),
        "linea": quote_payload.get("orbika", {}).get("linea"),
        "version": quote_payload.get("orbika", {}).get("version"),
        "ano": quote_payload.get("orbika", {}).get("ano"),
        "placa": quote_payload.get("orbika", {}).get("placa"),
        "vin": quote_payload.get("orbika", {}).get("vin"),
    }

    part_reviews = [
        run_part_review(quote_context=quote_context, part=part, reviewer=reviewer)
        for part in supplier_matching.get("parts", [])
    ]
    parts_with_agentic_matches = sum(1 for part in part_reviews if part["selected_count"] > 0)
    provider_hits: dict[str, int] = {}
    for part in part_reviews:
        provider_id = part.get("top_provider_id")
        if provider_id:
            provider_hits[provider_id] = provider_hits.get(provider_id, 0) + 1

    langsmith_enabled = bool(os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_TRACING_V2"))
    return {
        "generated_at": utc_now(),
        "base_supplier_matching_generated_at": supplier_matching.get("generated_at"),
        "review_mode": part_reviews[0]["reviewer_mode"] if part_reviews else "heuristic_fallback",
        "langgraph_available": LANGGRAPH_AVAILABLE,
        "langchain_available": LANGCHAIN_AVAILABLE,
        "langsmith_configured": langsmith_enabled,
        "model_name": model_name,
        "summary": {
            "parts_reviewed": len(part_reviews),
            "parts_with_agentic_matches": parts_with_agentic_matches,
            "provider_hits": dict(sorted(provider_hits.items())),
        },
        "parts": part_reviews,
    }


def enrich_quote_payload_with_agentic_review(
    quote_payload: dict[str, Any],
    *,
    limit_per_part: int = 5,
    model_name: str | None = None,
) -> dict[str, Any]:
    if not quote_payload.get("supplier_matching"):
        quote_payload["agentic_supplier_matching"] = {
            "generated_at": utc_now(),
            "review_mode": "skipped_missing_supplier_matching",
            "summary": {
                "parts_reviewed": 0,
                "parts_with_agentic_matches": 0,
                "provider_hits": {},
            },
            "parts": [],
            "notes": [
                "Agentic review was skipped because supplier_matching is missing from the quote payload."
            ],
        }
        return quote_payload

    quote_payload["agentic_supplier_matching"] = build_agentic_match_report(
        quote_payload,
        limit_per_part=limit_per_part,
        model_name=model_name,
    )
    return quote_payload


def write_trace_file(trace_dir: Path, quote_payload: dict[str, Any]) -> Path:
    trace_dir.mkdir(parents=True, exist_ok=True)
    quote_key = str(quote_payload.get("quote_key") or "unknown-quote")
    trace_path = trace_dir / f"{quote_key}.agentic_trace.json"
    trace_payload = {
        "quote_key": quote_key,
        "generated_at": utc_now(),
        "agentic_supplier_matching": quote_payload.get("agentic_supplier_matching", {}),
    }
    trace_path.write_text(json.dumps(trace_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return trace_path


def review_quotes_dir(
    *,
    quotes_dir: Path,
    trace_dir: Path | None = DEFAULT_TRACE_DIR,
    limit_per_part: int = 5,
    model_name: str | None = None,
) -> dict[str, Any]:
    reviewed = 0
    trace_paths: list[str] = []
    for quote_path in sorted(quotes_dir.glob("*.json")):
        payload = load_json(quote_path)
        enrich_quote_payload_with_agentic_review(
            payload,
            limit_per_part=limit_per_part,
            model_name=model_name,
        )
        write_quote_payload(quote_path, payload)
        reviewed += 1
        if trace_dir:
            trace_paths.append(str(write_trace_file(trace_dir, payload)))
    return {
        "quotes_reviewed": reviewed,
        "trace_paths": trace_paths,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Attach an optional LangGraph/LangChain-based agentic review on top of supplier_matching."
    )
    parser.add_argument("--quotes-dir", type=Path, default=DEFAULT_QUOTES_DIR)
    parser.add_argument("--trace-dir", type=Path, default=DEFAULT_TRACE_DIR)
    parser.add_argument("--limit-per-part", type=int, default=5)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--disable-traces", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    result = review_quotes_dir(
        quotes_dir=args.quotes_dir,
        trace_dir=None if args.disable_traces else args.trace_dir,
        limit_per_part=args.limit_per_part,
        model_name=args.model,
    )
    print(
        "Agentic supplier review completed: "
        f"{result['quotes_reviewed']} quote file(s) reviewed. "
        f"Trace files: {len(result['trace_paths'])}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
