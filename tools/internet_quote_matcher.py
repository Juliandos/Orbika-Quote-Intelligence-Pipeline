#!/usr/bin/env python3
"""Internet search matcher for quote parts."""

from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
import shutil
from functools import lru_cache
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from tools.supplier_quote_matcher import (
    PART_SIGNAL_COMPATIBILITY,
    STRICT_PART_FAMILIES,
    load_provider_catalog_index,
    infer_part_family,
    infer_primary_part_signal,
    match_quote_part,
    normalize_reference,
    normalize_text,
    part_family_is_compatible,
    token_set,
    vehicle_profile_from_quote_context,
    utc_now,
)

SEARCH_ENGINE_URL = "https://html.duckduckgo.com/html/"
GOOGLE_SEARCH_URL = "https://www.google.com/search"
ENABLE_ENV_VAR = "ORBIKA_ENABLE_INTERNET_SEARCH_MATCHES"
SEARCH_MODE_ENV = "ORBIKA_INTERNET_SEARCH_ENGINE"
SEARCH_BROWSER_ENV = "ORBIKA_INTERNET_SEARCH_BROWSER"
SEARCH_BROWSER_PATH_ENV = "PLAYWRIGHT_BROWSER_PATH"
SEARCH_HEADLESS_ENV = "ORBIKA_INTERNET_SEARCH_HEADLESS"
PROVIDER_SEARCH_LIMIT_ENV = "ORBIKA_INTERNET_PROVIDER_SEARCH_LIMIT"
PAGE_EVIDENCE_TIMEOUT_ENV = "ORBIKA_INTERNET_PAGE_TIMEOUT_SECONDS"
DEFAULT_LIMIT = 5
MAX_SEARCH_RESULTS = 8
MIN_SCORE = 70
PROVIDERS_ROOT = Path("supplier_catalog/providers")
KNOWN_PROVIDER_PRIORITY = (
    "imotriz",
    "importadorasasociadas",
    "partcar",
    "redpuestos",
    "repuestera",
    "totus",
    "procar",
    "latiendadelrepuesto",
    "autopartesya",
    "motorpartes",
    "autorecambiosltda",
    "tusautopartes",
)
CSV_FIELDS = [
    "item_type",
    "provider_type",
    "title",
    "product_name",
    "detail_url",
    "product_url",
    "category_name",
    "subcategory_name",
    "brand",
    "reference",
    "sku",
    "vehicle_scope",
    "match_type",
    "match_confidence",
]


@dataclass(frozen=True)
class SearchHit:
    url: str
    title: str
    snippet: str
    domain: str
    search_source: str = "unknown"


@dataclass(frozen=True)
class KnownProvider:
    provider_id: str
    display_name: str
    domains: tuple[str, ...]
    snapshot_path: Path | None


class _DuckDuckGoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._capture_title = False
        self._capture_snippet = False
        self._current_href: str | None = None
        self._title_buffer: list[str] = []
        self._snippet_buffer: list[str] = []
        self.results: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key: value or "" for key, value in attrs}
        if tag == "a" and "result__a" in attrs_dict.get("class", ""):
            self._capture_title = True
            self._current_href = attrs_dict.get("href") or ""
            self._title_buffer = []
        elif tag == "a" and "result__snippet" in attrs_dict.get("class", ""):
            self._capture_snippet = True
            self._snippet_buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capture_title and self._current_href:
            self.results.append(
                {
                    "url": self._current_href,
                    "title": html.unescape("".join(self._title_buffer).strip()),
                    "snippet": "",
                }
            )
            self._capture_title = False
            self._current_href = None
        elif tag == "a" and self._capture_snippet:
            if self.results:
                self.results[-1]["snippet"] = html.unescape("".join(self._snippet_buffer).strip())
            self._capture_snippet = False

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self._title_buffer.append(data)
        elif self._capture_snippet:
            self._snippet_buffer.append(data)


def internet_search_enabled() -> bool:
    value = os.environ.get(ENABLE_ENV_VAR, "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(text).split())


def _env_value(name: str, default: str = "") -> str:
    value = os.environ.get(name, default).strip()
    return value if value else default


def _search_mode() -> str:
    return _env_value(SEARCH_MODE_ENV, "browser").lower()


def _search_headless() -> bool:
    value = os.environ.get(SEARCH_HEADLESS_ENV, "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def detect_browser_executable() -> str | None:
    configured = _env_value(SEARCH_BROWSER_PATH_ENV)
    if configured:
        return configured
    browser_pref = _env_value(SEARCH_BROWSER_ENV, _search_mode())
    candidates_by_pref = {
        "brave": ("brave-browser", "brave", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "msedge"),
        "chrome": ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "msedge", "brave-browser", "brave"),
        "chromium": ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "microsoft-edge", "msedge", "brave-browser", "brave"),
        "edge": ("microsoft-edge", "msedge", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "brave-browser", "brave"),
    }
    candidates = candidates_by_pref.get(browser_pref, candidates_by_pref["chrome"])
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default)).strip()))
    except ValueError:
        return default


def _latest_snapshot_json(provider_dir: Path) -> Path | None:
    snapshots_root = provider_dir / "snapshots"
    if not snapshots_root.exists():
        return None
    candidates = sorted(snapshots_root.glob("*/extracted.json"))
    return candidates[-1] if candidates else None


def _domain_candidates(*urls: str | None) -> tuple[str, ...]:
    domains: list[str] = []
    for url in urls:
        if not url:
            continue
        parsed = urlparse(str(url))
        host = parsed.netloc.lower().removeprefix("www.")
        if host and host not in domains:
            domains.append(host)
    return tuple(domains)


def _known_providers() -> list[KnownProvider]:
    providers: list[KnownProvider] = []
    if not PROVIDERS_ROOT.exists():
        return providers
    priority = {provider_id: index for index, provider_id in enumerate(KNOWN_PROVIDER_PRIORITY)}
    for provider_dir in PROVIDERS_ROOT.iterdir():
        metadata_path = provider_dir / "provider.json"
        if not provider_dir.is_dir() or not metadata_path.exists():
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        provider_id = str(metadata.get("provider_id") or provider_dir.name)
        domains = _domain_candidates(
            metadata.get("website"),
            metadata.get("catalog_root_url"),
            (metadata.get("catalog") or {}).get("root_url"),
        )
        if not domains:
            continue
        providers.append(
            KnownProvider(
                provider_id=provider_id,
                display_name=str(metadata.get("display_name") or provider_id.title()),
                domains=domains,
                snapshot_path=_latest_snapshot_json(provider_dir),
            )
        )
    providers.sort(key=lambda item: (priority.get(item.provider_id, 999), item.provider_id))
    return providers


def _provider_for_url(url: str) -> KnownProvider | None:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if not host:
        return None
    for provider in _known_providers():
        if any(host == domain or host.endswith(f".{domain}") for domain in provider.domains):
            return provider
    return None


def _http_get(url: str, timeout: int = 12) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 OrbikaQuoteIntelligence/1.0",
            "Accept-Language": "es-CO,es;q=0.9,en;q=0.7",
        },
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - intentional web fetch.
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read(500_000).decode(charset, errors="ignore")


def _extract_url(href: str) -> str:
    parsed = urlparse(href)
    if parsed.path.startswith("/l/") or ("google." in parsed.netloc and parsed.path.startswith("/url")):
        query = parse_qs(parsed.query)
        for key in ("uddg", "u", "url", "q"):
            if key in query and query[key]:
                return unquote(query[key][0])
    if href.startswith("//"):
        return f"https:{href}"
    return urljoin(SEARCH_ENGINE_URL, href)


def _google_result_rows(page, limit: int) -> list[dict[str, str]]:
    try:
        rows = page.evaluate(
            """
            (limit) => {
              const anchors = Array.from(document.querySelectorAll('div#search a[href], a[href]'));
              const seen = new Set();
              const items = [];
              for (const anchor of anchors) {
                const h3 = anchor.querySelector('h3');
                if (!h3) continue;
                const title = (h3.textContent || '').trim();
                const href = anchor.href || anchor.getAttribute('href') || '';
                if (!title || !href || seen.has(href)) continue;
                let snippet = '';
                const scope = anchor.closest('div') || anchor.parentElement;
                if (scope) {
                  const textNodes = Array.from(scope.querySelectorAll('div, span, p'));
                  for (const node of textNodes) {
                    const text = (node.innerText || node.textContent || '').trim();
                    if (text && text !== title && text.length > 20 && text.length < 700) {
                      snippet = text;
                      break;
                    }
                  }
                }
                items.push({url: href, title, snippet});
                seen.add(href);
                if (items.length >= limit) break;
              }
              return items;
            }
            """,
            limit,
        )
    except Exception:
        return []
    return [row for row in rows if isinstance(row, dict)]


def _dismiss_search_popups(page) -> None:
    selectors = (
        "button:has-text('Aceptar todo')",
        "button:has-text('Acepto')",
        "button:has-text('Aceptar')",
        "button:has-text('I agree')",
        "button:has-text('Agree')",
        "button:has-text('Got it')",
        "[aria-label*='accept' i]",
        "[aria-label*='acept' i]",
        "[aria-label*='close' i]",
        "[aria-label*='cerrar' i]",
    )
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() and locator.is_visible(timeout=500):
                locator.click(timeout=1200, force=True)
                page.wait_for_timeout(150)
        except Exception:
            continue
    try:
        page.keyboard.press('Escape')
    except Exception:
        pass


def _browser_query_search(query: str, limit: int = MAX_SEARCH_RESULTS) -> list[SearchHit]:
    if not query:
        return []
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return []
    browser_path = detect_browser_executable()
    launch_kwargs: dict[str, Any] = {"headless": _search_headless()}
    if browser_path:
        launch_kwargs["executable_path"] = browser_path
    variants = _query_variants(query)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**launch_kwargs)
            try:
                context = browser.new_context(
                    locale="es-CO",
                    viewport={"width": 1365, "height": 900},
                    extra_http_headers={"Accept-Language": "es-CO,es;q=0.9,en;q=0.7"},
                )
                page = context.new_page()
                hits: list[SearchHit] = []
                seen: set[str] = set()
                for variant in variants:
                    params = {
                        "q": variant,
                        "hl": "es",
                        "gl": "co",
                        "num": "10",
                        "pws": "0",
                        "safe": "off",
                    }
                    try:
                        page.goto(f"{GOOGLE_SEARCH_URL}?{urlencode(params)}", wait_until="domcontentloaded", timeout=12000)
                    except Exception:
                        continue
                    _dismiss_search_popups(page)
                    page.wait_for_timeout(600)
                    for result in _google_result_rows(page, limit):
                        url = _extract_url(result.get("url", ""))
                        parsed = urlparse(url)
                        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                            continue
                        normalized = parsed.geturl()
                        if normalized in seen:
                            continue
                        seen.add(normalized)
                        hits.append(
                            SearchHit(
                                url=normalized,
                                title=_clean_text(result.get("title")) or normalized,
                                snippet=_clean_text(result.get("snippet")),
                                domain=parsed.netloc.lower(),
                                search_source="google_browser",
                            )
                        )
                        if len(hits) >= limit:
                            return _rank_hits_by_provider(hits)
                return _rank_hits_by_provider(hits)
            finally:
                try:
                    browser.close()
                except Exception:
                    pass
    except Exception:
        return []


def _build_query(part: dict[str, Any], quote_context: dict[str, Any]) -> str:
    values = [
        _first_text(part.get("part_name"), part.get("name")),
        _first_text(quote_context.get("marca")),
        _first_text(quote_context.get("linea")),
    ]
    query = re.sub(r"\s+", " ", " ".join(value for value in values if value)).strip()
    if "colombia" not in normalize_text(query):
        query = f"{query} Colombia".strip()
    return query


def _query_variants(query: str) -> list[str]:
    base = re.sub(r"\s+", " ", query).strip()
    variants: list[str] = []
    provider_limit = _env_int(PROVIDER_SEARCH_LIMIT_ENV, 2)
    for provider in _known_providers()[:provider_limit]:
        domain = provider.domains[0]
        variants.append(f"{base} site:{domain}")
    variants.append(base)
    deduped: list[str] = []
    for variant in variants:
        if variant and variant not in deduped:
            deduped.append(variant)
    return deduped


def _rank_hits_by_provider(hits: list[SearchHit]) -> list[SearchHit]:
    def rank(hit: SearchHit) -> tuple[int, str]:
        provider = _provider_for_url(hit.url)
        if not provider:
            return (999, hit.domain)
        try:
            provider_rank = KNOWN_PROVIDER_PRIORITY.index(provider.provider_id)
        except ValueError:
            provider_rank = 100
        return (provider_rank, hit.domain)
    return sorted(hits, key=rank)


def _duckduckgo_query_search(query: str, limit: int = MAX_SEARCH_RESULTS) -> list[SearchHit]:
    if not query:
        return []
    try:
        html_text = _http_get(f"{SEARCH_ENGINE_URL}?q={quote_plus(query)}")
    except Exception:
        return []

    parser = _DuckDuckGoParser()
    parser.feed(html_text)
    hits: list[SearchHit] = []
    seen: set[str] = set()
    for result in parser.results:
        url = _extract_url(result["url"])
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        normalized = parsed.geturl()
        if normalized in seen:
            continue
        seen.add(normalized)
        hits.append(
            SearchHit(
                url=normalized,
                title=_clean_text(result.get("title")) or normalized,
                snippet=_clean_text(result.get("snippet")),
                domain=parsed.netloc.lower(),
                search_source="duckduckgo_html",
            )
        )
        if len(hits) >= limit:
            break
    return hits


REDIS_URL_ENV = "ORBIKA_REDIS_URL"
CACHE_TTL_SEARCH = 86400
CACHE_TTL_EVIDENCE = 86400


@lru_cache(maxsize=1)
def _redis_client() -> Any:
    url = os.environ.get(REDIS_URL_ENV, "").strip()
    if not url:
        return None
    try:
        import redis  # type: ignore
        client = redis.Redis.from_url(url, socket_timeout=3, socket_connect_timeout=3)
        client.ping()
        return client
    except Exception:
        return None


def _cache_get(key: str) -> Any:
    client = _redis_client()
    if client is None:
        return None
    try:
        raw = client.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _cache_set(key: str, value: Any, ttl: int) -> None:
    client = _redis_client()
    if client is None:
        return
    try:
        client.setex(key, ttl, json.dumps(value, ensure_ascii=False))
    except Exception:
        pass


SEARXNG_URL_ENV = "ORBIKA_SEARXNG_URL"


def _searxng_query_search(query: str, limit: int = MAX_SEARCH_RESULTS) -> list[SearchHit]:
    base = os.environ.get(SEARXNG_URL_ENV, "http://searxng:8080").strip().rstrip("/")
    if not base:
        return []
    cache_key = "orbika:searxng:" + hashlib.md5((query + "|" + str(limit)).encode("utf-8")).hexdigest()
    cached = _cache_get(cache_key)
    if cached is not None:
        return [SearchHit(**item) for item in cached]
    params = urlencode({"q": query, "format": "json", "language": "es-CO", "safesearch": "0"})
    request = Request(base + "/search?" + params, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 - intentional web fetch.
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception:
        return []
    hits: list[SearchHit] = []
    for result in payload.get("results", []):
        url = str(result.get("url") or "").strip()
        if not url:
            continue
        domain = urlparse(url).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        hits.append(
            SearchHit(
                url=url,
                title=_clean_text(result.get("title")),
                snippet=_clean_text(result.get("content")),
                domain=domain,
                search_source="searxng",
            )
        )
        if len(hits) >= limit:
            break
    _cache_set(cache_key, [{"url": h.url, "title": h.title, "snippet": h.snippet, "domain": h.domain, "search_source": h.search_source} for h in hits], CACHE_TTL_SEARCH)
    return hits


def _query_search(query: str, limit: int = MAX_SEARCH_RESULTS) -> list[SearchHit]:
    if not query:
        return []
    mode = _search_mode()
    if mode in {"searxng", "searx"}:
        searx_hits = _searxng_query_search(query, limit)
        if searx_hits:
            return searx_hits
    search_sources = ["browser", "duckduckgo"] if mode not in {"duckduckgo", "ddg"} else ["duckduckgo"]
    if mode in {"google", "browser", "chrome", "brave", "chromium", "edge"}:
        search_sources = ["browser", "duckduckgo"]
    for source in search_sources:
        hits = _browser_query_search(query, limit) if source == "browser" else _duckduckgo_query_search(query, limit)
        if hits:
            return hits
    return []


@lru_cache(maxsize=2)
def _catalog_index(catalog_source: str = "db-first") -> Any:
    return load_provider_catalog_index(PROVIDERS_ROOT, catalog_source=catalog_source)


def _catalog_fallback_matches(
    *,
    quote_context: dict[str, Any],
    part: dict[str, Any],
    limit_per_part: int,
    catalog_source: str = "db-first",
) -> list[dict[str, Any]]:
    index = _catalog_index(catalog_source)
    fallback_part = {
        "name": _first_text(part.get("name"), part.get("part_name")),
        "reference": _first_text(part.get("reference"), part.get("requested_reference")),
        "quantity": part.get("quantity"),
        "reference_validation_text": part.get("reference_validation_text"),
    }
    part_report = match_quote_part(
        part=fallback_part,
        quote_context=quote_context,
        index=index,
        preferences={},
        limit=max(1, limit_per_part),
    )
    matches: list[dict[str, Any]] = []
    query = _build_query(part, quote_context)
    for match in part_report.get("matches", []):
        candidate = dict(match)
        candidate["source_type"] = "internet_search"
        candidate["explanation_source"] = "catalog"
        candidate["agentic_comment"] = candidate.get("summary") or "Busqueda local sobre catalogos existentes."
        candidate["confidence"] = "validated" if not candidate.get("requires_manual_confirmation") else "probable"
        candidate["evidence"] = {
            "query": query,
            "search_source": "provider_catalog_fallback",
            "search_title": candidate.get("product_name") or "",
            "search_snippet": candidate.get("compatibility_summary") or candidate.get("summary") or "",
            "page_title": "",
            "page_description": "",
            "page_h1": "",
        }
        matches.append(candidate)
    return matches


def _page_evidence(url: str) -> dict[str, str]:
    evidence_key = "orbika:evidence:" + hashlib.md5(url.encode("utf-8")).hexdigest()
    cached_evidence = _cache_get(evidence_key)
    if cached_evidence is not None:
        return cached_evidence
    try:
        html_text = _http_get(url, timeout=_env_int(PAGE_EVIDENCE_TIMEOUT_ENV, 5))
    except Exception:
        return {}
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
    desc_match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        html_text,
        re.IGNORECASE | re.DOTALL,
    )
    h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.IGNORECASE | re.DOTALL)
    result = {
        "page_title": _clean_text(title_match.group(1)) if title_match else "",
        "page_description": _clean_text(desc_match.group(1)) if desc_match else "",
        "page_h1": _clean_text(h1_match.group(1)) if h1_match else "",
        "page_text": _clean_text(html_text)[:2000],
    }
    _cache_set(evidence_key, result, CACHE_TTL_EVIDENCE)
    return result


def _candidate_family_text(candidate: dict[str, Any], evidence: dict[str, str]) -> str:
    return " ".join(
        value
        for value in (
            _first_text(candidate.get("title")),
            _first_text(candidate.get("snippet")),
            evidence.get("page_title"),
            evidence.get("page_h1"),
            evidence.get("page_description"),
            evidence.get("page_text"),
        )
        if value
    )


def _extract_reference_from_text(*values: str | None) -> str | None:
    joined = " ".join(value or "" for value in values)
    patterns = (
        r"\b[A-Z0-9]{3,}[-/][A-Z0-9]{3,}(?:[-/][A-Z0-9]+)*\b",
        r"\b[A-Z0-9]{6,}\b",
    )
    for pattern in patterns:
        match = re.search(pattern, joined.upper())
        if match:
            return match.group(0)
    return None


def _provider_snapshot_record(
    *,
    provider: KnownProvider,
    candidate: dict[str, Any],
    quote_context: dict[str, Any],
    part: dict[str, Any],
) -> dict[str, Any]:
    evidence = candidate.get("evidence") or {}
    product_name = _first_text(candidate.get("product_name"), evidence.get("search_title"), part.get("part_name"), part.get("name")) or "Repuesto"
    detail_url = str(candidate.get("detail_url") or "")
    reference = _first_text(
        candidate.get("reference"),
        _extract_reference_from_text(detail_url, product_name, evidence.get("search_snippet"), evidence.get("page_title")),
    )
    description = _first_text(evidence.get("page_description"), evidence.get("search_snippet"), product_name)
    brand = _first_text(quote_context.get("marca"), candidate.get("brand"))
    category_name = _first_text(quote_context.get("linea"), candidate.get("category_name"))
    tokens = sorted(
        token_set(
            product_name,
            reference,
            candidate.get("sku"),
            brand,
            category_name,
            description,
            "Autos",
            provider.display_name,
            "internet search",
        )
    )
    return {
        "item_type": "product",
        "provider_type": "product_catalog",
        "title": None,
        "product_name": product_name,
        "detail_url": detail_url,
        "product_url": detail_url,
        "category_name": category_name,
        "subcategory_name": None,
        "brand": brand,
        "reference": reference,
        "sku": normalize_reference(reference) or reference,
        "supplier_item_code": normalize_reference(reference) or reference,
        "description": description,
        "vehicle_scope": "Autos",
        "image_url": None,
        "source_page_url": evidence.get("query") or "internet_search",
        "page_number": 1,
        "match_type": "web_validated",
        "match_confidence": "high",
        "requires_manual_confirmation": False,
        "searchable_tokens": tokens,
    }


def _write_snapshot_csv(csv_path: Path, products: list[dict[str, Any]]) -> None:
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for product in products:
            writer.writerow({field: product.get(field) for field in CSV_FIELDS})


def _append_candidate_to_provider_snapshot(
    *,
    candidate: dict[str, Any],
    quote_context: dict[str, Any],
    part: dict[str, Any],
) -> dict[str, Any]:
    detail_url = str(candidate.get("detail_url") or "")
    provider = _provider_for_url(detail_url)
    if not provider or not provider.snapshot_path or not provider.snapshot_path.exists():
        return {"status": "skipped", "reason": "provider snapshot unavailable"}
    try:
        payload = json.loads(provider.snapshot_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"status": "failed", "reason": f"snapshot read failed: {exc}"}
    products = payload.get("products")
    if not isinstance(products, list):
        return {"status": "failed", "reason": "snapshot products is not a list"}
    normalized_url = detail_url.rstrip("/")
    for product in products:
        if not isinstance(product, dict):
            continue
        existing_url = str(product.get("detail_url") or product.get("product_url") or "").rstrip("/")
        if existing_url == normalized_url:
            return {"status": "exists", "provider_id": provider.provider_id, "snapshot_path": str(provider.snapshot_path)}
    record = _provider_snapshot_record(provider=provider, candidate=candidate, quote_context=quote_context, part=part)
    products.append(record)
    notes = payload.setdefault("notes", [])
    note = f"Producto agregado desde busqueda web validada: {record['product_name']} ({detail_url})"
    if isinstance(notes, list) and note not in notes:
        notes.append(note)
    payload["products"] = products
    provider.snapshot_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_snapshot_csv(provider.snapshot_path.with_name("products.csv"), [p for p in products if isinstance(p, dict)])
    return {
        "status": "added",
        "provider_id": provider.provider_id,
        "provider_name": provider.display_name,
        "snapshot_path": str(provider.snapshot_path),
        "product_name": record["product_name"],
    }


def _score_candidate(
    *,
    quote_context: dict[str, Any],
    part: dict[str, Any],
    hit: SearchHit,
    evidence: dict[str, str],
) -> dict[str, Any] | None:
    requested_name = _first_text(part.get("part_name"), part.get("name")) or "Repuesto"
    requested_reference = normalize_reference(_first_text(part.get("requested_reference"), part.get("reference")))
    requested_family = infer_part_family(requested_name, requested_reference)
    requested_signal = infer_primary_part_signal(requested_name, requested_reference)
    candidate_text = _candidate_family_text({"title": hit.title, "snippet": hit.snippet}, evidence)
    candidate_family = infer_part_family(candidate_text, requested_reference)
    candidate_signal = infer_primary_part_signal(hit.title, hit.snippet, evidence.get("page_title"), requested_reference)

    if requested_family and candidate_family:
        if requested_family in STRICT_PART_FAMILIES and requested_family != candidate_family:
            return None
        if requested_family != candidate_family and not part_family_is_compatible(requested_family, candidate_family):
            return None
    if requested_signal:
        allowed = PART_SIGNAL_COMPATIBILITY.get(requested_signal, {requested_signal})
        if candidate_signal and candidate_signal not in allowed:
            return None

    provider = _provider_for_url(hit.url)
    vehicle = vehicle_profile_from_quote_context(quote_context)
    candidate_tokens = token_set(candidate_text)
    requested_tokens = token_set(requested_name, _first_text(part.get("requested_reference"), part.get("reference")))
    overlap_tokens = requested_tokens & candidate_tokens
    requested_name_normalized = normalize_text(requested_name)
    candidate_text_normalized = normalize_text(candidate_text)
    score = 0
    reasons: list[str] = []
    if requested_family and candidate_family and requested_family == candidate_family:
        score += 30
        reasons.append("misma familia de repuesto")
    if requested_signal and candidate_signal and requested_signal == candidate_signal:
        score += 10
        reasons.append("mismo tipo de repuesto")
    if requested_reference and requested_reference in candidate_text_normalized:
        score += 35
        reasons.append("referencia visible")
    elif not requested_reference:
        visible_ref = _extract_reference_from_text(hit.url, hit.title, hit.snippet, evidence.get("page_title"))
        if visible_ref:
            score += 8
            reasons.append("referencia visible en resultado web")
    if requested_name_normalized and requested_name_normalized in candidate_text_normalized:
        score += 25
        reasons.append("nombre solicitado visible")
    elif len(overlap_tokens) >= 2:
        score += 18
        reasons.append("tokens principales del repuesto visibles")
    if len(vehicle.brand_tokens & candidate_tokens):
        score += 15
        reasons.append("marca del vehiculo visible")
    if len(vehicle.line_tokens & candidate_tokens):
        score += 18
        reasons.append("linea del vehiculo visible")
    if len(vehicle.version_tokens & candidate_tokens):
        score += 4
    if overlap_tokens:
        score += min(len(overlap_tokens) * 5, 15)
    if provider:
        score += 12
        reasons.append(f"proveedor existente: {provider.display_name}")

    if score < MIN_SCORE:
        return None

    provider_name = provider.display_name if provider else hit.domain.replace("www.", "")
    provider_id = provider.provider_id if provider else re.sub(r"[^a-z0-9]+", "_", hit.domain.lower()).strip("_")
    product_name = _first_text(evidence.get("page_h1"), evidence.get("page_title"), hit.title) or requested_name
    reference = requested_reference or _extract_reference_from_text(hit.url, product_name, hit.snippet, evidence.get("page_title"))
    comment = "Busqueda web validada por nombre, vehiculo y evidencia visible."
    return {
        "provider_id": provider_id,
        "provider_name": provider_name,
        "product_name": product_name,
        "reference": reference or None,
        "sku": normalize_reference(reference) or None,
        "brand": _first_text(quote_context.get("marca")),
        "category_name": "internet_search",
        "subcategory_name": None,
        "detail_url": hit.url,
        "price": None,
        "currency": "COP",
        "availability": None,
        "match_type": "web_validated",
        "score_percent": max(0, min(int(score), 100)),
        "reasons": reasons,
        "risk_flags": [],
        "compatibility_state": "compatible",
        "compatibility_summary": "Validado por busqueda en internet",
        "compatibility_warnings": [],
        "source_type": "internet_search",
        "explanation_source": "web",
        "agentic_comment": comment,
        "confidence": "validated" if provider else "external_validated",
        "evidence": {
            "query": _build_query(part, quote_context),
            "search_source": hit.search_source,
            "search_title": hit.title,
            "search_snippet": hit.snippet,
            "page_title": evidence.get("page_title", ""),
            "page_description": evidence.get("page_description", ""),
            "page_h1": evidence.get("page_h1", ""),
        },
    }


def _persist_internet_product_to_db(candidate: dict[str, Any]) -> None:
    detail_url = str(candidate.get("detail_url") or "").strip()
    if not detail_url:
        return
    provider = _provider_for_url(detail_url)
    if provider is None:
        return
    try:
        from tools.postgres_quote_persistence import database_url_from_env
        import psycopg
    except Exception:
        return
    database_url = database_url_from_env()
    if not database_url:
        return
    detail_url_hash = hashlib.md5(detail_url.encode("utf-8")).hexdigest()
    title = _first_text(candidate.get("product_name"), candidate.get("title")) or "Producto web"
    try:
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM provider_products WHERE detail_url_hash = %s LIMIT 1", (detail_url_hash,))
                if cur.fetchone():
                    return
                cur.execute("SELECT id FROM provider_catalog_snapshots WHERE provider_id = %s AND status = 'web_search' LIMIT 1", (provider.provider_id,))
                row = cur.fetchone()
                if row:
                    snapshot_id = row[0]
                else:
                    cur.execute(
                        "INSERT INTO provider_catalog_snapshots (provider_id, provider_name, provider_type, snapshot_date, source_path, source_hash, product_count, provider_metadata, snapshot_metadata, notes, status, created_at, loaded_at) "
                        "VALUES (%s, %s, %s, CURRENT_DATE, %s, %s, 0, '{}'::jsonb, '{}'::jsonb, '[]'::jsonb, 'web_search', now(), now()) RETURNING id",
                        (provider.provider_id, provider.display_name, "marketplace", "web-search:" + provider.provider_id, "web-search:" + provider.provider_id),
                    )
                    snapshot_id = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO provider_products (snapshot_id, provider_id, provider_name, provider_type, title, reference, sku, detail_url, detail_url_hash, raw_match_type, requires_manual_confirmation, searchable_text, searchable_tokens, taxonomy_labels, notes, raw_payload, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, %s, now(), now())",
                    (snapshot_id, provider.provider_id, provider.display_name, "marketplace", title,
                     _first_text(candidate.get("reference")), _first_text(candidate.get("sku")),
                     detail_url, detail_url_hash, "internet_search", title,
                     json.dumps({"source": "internet_search", "detail_url": detail_url}, ensure_ascii=False)),
                )
                conn.commit()
    except Exception:
        return


def build_internet_search_part_report(
    *,
    quote_context: dict[str, Any],
    part: dict[str, Any],
    limit_per_part: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    query = _build_query(part, quote_context)
    hits = _query_search(query)
    selected: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    for hit in hits:
        evidence = _page_evidence(hit.url)
        if not evidence:
            diagnostics.append(f"Sin detalle rapido para {hit.url}; se uso evidencia SERP.")
        candidate = _score_candidate(quote_context=quote_context, part=part, hit=hit, evidence=evidence or {})
        if candidate:
            snapshot_update = _append_candidate_to_provider_snapshot(
                candidate=candidate,
                quote_context=quote_context,
                part=part,
            )
            candidate["snapshot_update"] = snapshot_update
            _persist_internet_product_to_db(candidate)
            selected.append(candidate)
    if not selected:
        diagnostics.append("Sin resultados web visibles; se uso busqueda local sobre catalogos existentes.")
        selected = _catalog_fallback_matches(
            quote_context=quote_context,
            part=part,
            limit_per_part=limit_per_part,
            catalog_source="db-first",
        )
    if not selected:
        diagnostics.append("PostgreSQL no devolvio candidatos utiles; se uso el snapshot vivo del proveedor como rescate.")
        selected = _catalog_fallback_matches(
            quote_context=quote_context,
            part=part,
            limit_per_part=limit_per_part,
            catalog_source="snapshots",
        )
    selected.sort(
        key=lambda item: (
            1 if (item.get("snapshot_update") or {}).get("provider_id") else 0,
            item.get("score_percent", 0),
            item.get("provider_name", ""),
            item.get("product_name", ""),
        ),
        reverse=True,
    )
    selected = selected[:limit_per_part]
    return {
        "part_name": _first_text(part.get("part_name"), part.get("name")) or "Repuesto",
        "requested_reference": _first_text(part.get("requested_reference"), part.get("reference")),
        "query": query,
        "query_variants": _query_variants(query),
        "top_provider_id": selected[0].get("provider_id") if selected else None,
        "top_score_percent": selected[0].get("score_percent") if selected else 0,
        "summary_comment": selected[0].get("agentic_comment") if selected else "Sin resultados web validados.",
        "risk_notes": diagnostics,
        "preference_notes": [],
        "selected_matches": selected,
    }


def build_internet_search_report(
    quote_payload: dict[str, Any],
    *,
    limit_per_part: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    orbika = quote_payload.get("orbika", {}) or {}
    supplier_matching = quote_payload.get("supplier_matching", {}) or {}
    if orbika.get("repuestos_count") == 0 or quote_payload.get("repuestos_cotizados") == 0:
        return {
            "generated_at": utc_now(),
            "review_mode": "skipped_empty_quote",
            "enabled": internet_search_enabled(),
            "summary": {"parts_reviewed": 0, "parts_with_internet_matches": 0, "provider_hits": {}},
            "parts": [],
            "notes": ["Busqueda en internet omitida porque la cotizacion esta vacia."],
        }
    quote_context = {
        "marca": orbika.get("marca"),
        "linea": orbika.get("linea"),
        "version": orbika.get("version"),
        "ano": orbika.get("ano"),
        "placa": orbika.get("placa"),
        "vin": orbika.get("vin"),
    }
    parts_source = supplier_matching.get("parts") or orbika.get("parts") or []
    part_reports = [
        build_internet_search_part_report(quote_context=quote_context, part=part, limit_per_part=limit_per_part)
        for part in parts_source
        if isinstance(part, dict)
    ]
    provider_hits: dict[str, int] = {}
    for part in part_reports:
        provider_id = part.get("top_provider_id")
        if provider_id:
            provider_hits[provider_id] = provider_hits.get(provider_id, 0) + 1
    return {
        "generated_at": utc_now(),
        "review_mode": "internet_search",
        "enabled": internet_search_enabled() or bool(part_reports),
        "summary": {
            "parts_reviewed": len(part_reports),
            "parts_with_internet_matches": sum(1 for part in part_reports if part["selected_matches"]),
            "provider_hits": dict(sorted(provider_hits.items())),
        },
        "parts": part_reports,
        "notes": [],
    }

