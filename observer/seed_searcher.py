from __future__ import annotations

import asyncio
import os
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import psycopg2
import requests
from dotenv import load_dotenv

from dataclass.dataclass import SearchHit, SearchRequest, SearchResult, SeedDiscovery
from observer.observe_supervisor import ObserveStackItem
from observer.search_log import SearchLogStore, SearchRunLogRecord

load_dotenv(encoding="utf-8-sig")

COURSE_HINT_KEYWORDS = (
    "course",
    "courses",
    "program",
    "programmes",
    "degree",
    "degrees",
    "undergraduate",
    "postgraduate",
    "study",
    "academics",
)

NEGATIVE_HINT_KEYWORDS = (
    "news",
    "event",
    "blog",
    "ranking",
    "rankings",
    "wikipedia",
    "linkedin",
    "facebook",
    "x.com",
    "twitter",
)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

MAX_PROBE_URLS = 12
PROBE_CONCURRENCY = 6
MAX_INTERNAL_LINKS_PER_DOMAIN = 16
MAX_FALLBACK_QUERIES = 2

class BraveSearchAPI:
    """Brave Search API の薄いラッパー。"""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("BRAVE_API_KEY")
        self.api_type = "brave"
        self._client_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "X-Subscription-Token": self.api_key or "",
        }

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str, num_results: int = 10) -> list[dict[str, str]]:
        if not self.enabled:
            return []

        url = "https://api.search.brave.com/res/v1/web/search"
        params = {"q": query, "count": num_results}

        response = httpx.get(url, params=params, headers=self._client_headers, timeout=12)
        response.raise_for_status()
        return self._extract_results(response.json())

    @staticmethod
    def _extract_results(payload: dict[str, Any]) -> list[dict[str, str]]:
        web = payload.get("web") or {}
        raw_results = web.get("results") or []
        results: list[dict[str, str]] = []
        for item in raw_results:
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            results.append(
                {
                    "url": url,
                    "title": str(item.get("title") or "").strip(),
                    "snippet": str(item.get("description") or "").strip(),
                }
            )
        return results


def _get_db_params() -> dict[str, Any] | None:
    required_keys = ["DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_PORT"]
    if any(not os.getenv(key) for key in required_keys):
        return None
    return {
        "host": os.getenv("DB_HOST"),
        "dbname": os.getenv("DB_NAME"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "port": int(os.getenv("DB_PORT", "5432")),
    }


def _root_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.netloc:
        return ""
    scheme = parsed.scheme or "https"
    return f"{scheme}://{parsed.netloc}"


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def _course_like_score(url: str, title: str, snippet: str, query: str) -> float:
    combined = f"{url} {title} {snippet}".lower()
    path = (urlparse(url).path or "").lower()
    domain = _domain(url)
    score = 0.0

    if any(keyword in path for keyword in COURSE_HINT_KEYWORDS):
        score += 4.0
    if any(keyword in combined for keyword in COURSE_HINT_KEYWORDS):
        score += 2.0
    if query and query.lower() in combined:
        score += 2.0
    if any(domain.endswith(suffix) for suffix in (".edu", ".ac.uk", ".ac.jp", ".edu.au")):
        score += 1.5
    if any(keyword in combined for keyword in NEGATIVE_HINT_KEYWORDS):
        score -= 3.0

    return score


def _is_university_like_domain(domain: str) -> bool:
    return any(domain.endswith(suffix) for suffix in (".edu", ".ac.uk", ".ac.jp", ".edu.au"))


def _tokens(text: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", text.lower()) if len(token) >= 3]


def _domain_match_bonus(domain: str, university_names: list[str]) -> float:
    domain_text = domain.lower()
    bonus = 0.0
    for name in university_names:
        for token in _tokens(name):
            if token in {"university", "college", "institute", "school"}:
                continue
            if token in domain_text:
                bonus += 0.8
    return bonus


def _extract_page_signals(url: str, title: str, snippet: str, html: str) -> tuple[bool, bool, float]:
    text = f"{url} {title} {snippet} {html[:50000]}".lower()
    path = (urlparse(url).path or "").lower()

    search_form_detected = "<form" in html.lower() and any(
        keyword in text for keyword in ("search", "finder", "filter", "query")
    )

    course_keyword_hits = sum(1 for keyword in COURSE_HINT_KEYWORDS if keyword in text)
    course_list_detected = course_keyword_hits >= 2 or "/program" in path or "/course" in path

    score_bonus = 0.0
    if search_form_detected:
        score_bonus += 1.0
    if course_list_detected:
        score_bonus += 3.0

    return search_form_detected, course_list_detected, score_bonus


def _apply_probe_to_hit(hit: SearchHit, html: str) -> SearchHit:
    search_form_detected, course_list_detected, score_bonus = _extract_page_signals(
        url=hit.url,
        title=hit.title,
        snippet=hit.snippet,
        html=html,
    )
    updated_score = hit.score + score_bonus
    return SearchHit(
        query=hit.query,
        url=hit.url,
        title=hit.title,
        snippet=hit.snippet,
        score=updated_score,
        is_course_like=hit.is_course_like or course_list_detected or updated_score >= 4.0,
        search_form_detected=search_form_detected,
        course_list_detected=course_list_detected,
    )


def _extract_internal_course_links(base_url: str, html: str) -> list[str]:
    if not html:
        return []

    base_domain = _domain(base_url)
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.IGNORECASE)
    links: list[str] = []
    for href in hrefs:
        href = href.strip()
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("javascript:"):
            continue
        absolute = urljoin(base_url, href)
        if _domain(absolute) != base_domain:
            continue
        path = (urlparse(absolute).path or "").lower()
        if any(keyword in path for keyword in COURSE_HINT_KEYWORDS):
            if absolute not in links:
                links.append(absolute)
        if len(links) >= MAX_INTERNAL_LINKS_PER_DOMAIN:
            break
    return links


def _probe_hit_sync(hit: SearchHit, errors: list[str]) -> SearchHit:
    try:
        response = requests.get(hit.url, headers=DEFAULT_HEADERS, timeout=10, allow_redirects=True)
        response.raise_for_status()
        content_type = (response.headers.get("content-type") or "").lower()
        html = response.text if "text/html" in content_type else ""
        return _apply_probe_to_hit(hit, html)
    except requests.RequestException as exc:
        errors.append(f"probe_sync url={hit.url}: {type(exc).__name__}: {exc}")
        return hit


async def _probe_hit_async(
    hit: SearchHit,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    errors: list[str],
) -> SearchHit:
    async with semaphore:
        try:
            response = await client.get(hit.url, follow_redirects=True)
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "").lower()
            html = response.text if "text/html" in content_type else ""
            return _apply_probe_to_hit(hit, html)
        except httpx.RequestError as exc:
            # 接続失敗時は requests で再試行
            errors.append(f"probe_httpx_failed url={hit.url}: {type(exc).__name__}: {exc}")
            return await asyncio.to_thread(_probe_hit_sync, hit, errors)
        except httpx.HTTPStatusError as exc:
            errors.append(f"probe_status_error url={hit.url}: {exc}")
            return hit


async def _probe_hits_async(hits: list[SearchHit], errors: list[str]) -> list[SearchHit]:
    if not hits:
        return hits
    semaphore = asyncio.Semaphore(PROBE_CONCURRENCY)
    async with httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=10) as client:
        tasks = [
            _probe_hit_async(hit=hit, client=client, semaphore=semaphore, errors=errors)
            for hit in hits
        ]
        return await asyncio.gather(*tasks)


def _probe_urls_sync(urls: list[str], errors: list[str]) -> list[SearchHit]:
    hits: list[SearchHit] = []
    for url in urls:
        try:
            response = requests.get(url, headers=DEFAULT_HEADERS, timeout=10, allow_redirects=True)
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "").lower()
            html = response.text if "text/html" in content_type else ""
            base_score = _course_like_score(url=url, title="", snippet="", query="internal-link") + 2.0
            base_hit = SearchHit(
                query="internal-link",
                url=url,
                title="",
                snippet="",
                score=base_score,
                is_course_like=base_score >= 4.0,
            )
            hits.append(_apply_probe_to_hit(base_hit, html))
        except requests.RequestException as exc:
            errors.append(f"internal_probe_sync url={url}: {type(exc).__name__}: {exc}")
    return hits


async def _probe_urls_async(urls: list[str], errors: list[str]) -> list[SearchHit]:
    semaphore = asyncio.Semaphore(PROBE_CONCURRENCY)

    async def _one(url: str, client: httpx.AsyncClient) -> SearchHit | None:
        async with semaphore:
            try:
                response = await client.get(url, follow_redirects=True)
                response.raise_for_status()
                content_type = (response.headers.get("content-type") or "").lower()
                html = response.text if "text/html" in content_type else ""
                base_score = _course_like_score(url=url, title="", snippet="", query="internal-link") + 2.0
                base_hit = SearchHit(
                    query="internal-link",
                    url=url,
                    title="",
                    snippet="",
                    score=base_score,
                    is_course_like=base_score >= 4.0,
                )
                return _apply_probe_to_hit(base_hit, html)
            except httpx.RequestError as exc:
                errors.append(f"internal_probe_httpx_failed url={url}: {type(exc).__name__}: {exc}")
                sync_hits = await asyncio.to_thread(_probe_urls_sync, [url], errors)
                return sync_hits[0] if sync_hits else None
            except httpx.HTTPStatusError as exc:
                errors.append(f"internal_probe_status_error url={url}: {exc}")
                return None

    async with httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=10) as client:
        results = await asyncio.gather(*[_one(url, client) for url in urls])
    return [hit for hit in results if hit is not None]


def _enrich_hits_with_probe(hits: list[SearchHit], errors: list[str]) -> list[SearchHit]:
    top_hits = hits[:MAX_PROBE_URLS]
    if not top_hits:
        return hits

    try:
        asyncio.get_running_loop()
        # 既存イベントループ内では同期フォールバックで安全に処理する。
        enriched_top = [_probe_hit_sync(hit, errors) for hit in top_hits]
    except RuntimeError:
        enriched_top = asyncio.run(_probe_hits_async(top_hits, errors))

    by_url: dict[str, SearchHit] = {hit.url: hit for hit in hits}
    for hit in enriched_top:
        by_url[hit.url] = hit
    return sorted(by_url.values(), key=lambda h: h.score, reverse=True)


def _discover_internal_links_from_official_hits(
    hits: list[SearchHit],
    official_domains: set[str],
    errors: list[str],
) -> list[str]:
    targets = [hit for hit in hits if _domain(hit.url) in official_domains][:MAX_PROBE_URLS]
    if not targets:
        return []

    discovered: list[str] = []
    for hit in targets:
        try:
            response = requests.get(hit.url, headers=DEFAULT_HEADERS, timeout=10, allow_redirects=True)
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "").lower()
            html = response.text if "text/html" in content_type else ""
            links = _extract_internal_course_links(hit.url, html)
            for link in links:
                if link not in discovered:
                    discovered.append(link)
        except requests.RequestException as exc:
            errors.append(f"internal_extract url={hit.url}: {type(exc).__name__}: {exc}")

    return discovered


def _select_official_domains(hits: list[SearchHit], university_names: list[str]) -> set[str]:
    domain_scores: dict[str, float] = {}
    for hit in hits:
        d = _domain(hit.url)
        if not d:
            continue
        score = hit.score
        if _is_university_like_domain(d):
            score += 2.0
        score += _domain_match_bonus(d, university_names)
        prev = domain_scores.get(d, float("-inf"))
        if score > prev:
            domain_scores[d] = score

    selected = sorted(domain_scores.items(), key=lambda x: x[1], reverse=True)[:3]
    return {d for d, _ in selected}


def _existing_root_urls(candidate_roots: list[str]) -> set[str]:
    db_params = _get_db_params()
    if not db_params or not candidate_roots:
        return set()

    existing: set[str] = set()
    try:
        with psycopg2.connect(**db_params) as conn:
            with conn.cursor() as cursor:
                for root in candidate_roots:
                    domain = _domain(root)
                    cursor.execute(
                        "SELECT 1 FROM seed_urls WHERE domain = %s AND root_url = %s LIMIT 1",
                        (domain, root),
                    )
                    if cursor.fetchone() is not None:
                        existing.add(root)
    except psycopg2.Error:
        # DB 不達時は探索を止めない
        return set()
    return existing


def _build_domain_discovery_queries(request: SearchRequest) -> list[str]:
    queries: list[str] = []
    for name in request.university_names:
        n = name.strip()
        if not n:
            continue
        queries.append(n)
        queries.append(f"{n} official site")
    # 候補が空なら source_domain を使った保険クエリを投げる
    if not queries and request.source_domain:
        queries.append(request.source_domain)
    deduped: list[str] = []
    seen: set[str] = set()
    for q in queries:
        if q not in seen:
            deduped.append(q)
            seen.add(q)
    return deduped[:6]


def _build_course_fallback_queries(official_domains: set[str], request: SearchRequest) -> list[str]:
    queries: list[str] = []
    for domain in sorted(official_domains):
        queries.append(f"site:{domain} courses")
        queries.append(f"site:{domain} programmes")
    if not queries:
        for name in request.university_names:
            n = name.strip()
            if n:
                queries.append(f"{n} courses")
                break
    deduped: list[str] = []
    seen: set[str] = set()
    for q in queries:
        if q not in seen:
            deduped.append(q)
            seen.add(q)
    return deduped[:MAX_FALLBACK_QUERIES]


def build_search_request(item: ObserveStackItem) -> SearchRequest:
    return SearchRequest(
        source_url=item.source_url,
        source_domain=_domain(item.source_url),
        university_names=list(item.university_names),
        content_type=item.page_analysis.content_type.value,
        candidate_lines=list(item.page_analysis.candidate_lines),
    )


def _build_result(request: SearchRequest, hits: list[SearchHit], errors: list[str]) -> SearchResult:
    root_candidates: list[str] = []
    for hit in hits:
        root = _root_url(hit.url)
        if root and root not in root_candidates:
            root_candidates.append(root)

    duplicate_roots = _existing_root_urls(root_candidates)
    filtered_roots = [root for root in root_candidates if root not in duplicate_roots]

    detailed_seed_urls = [
        hit.url
        for hit in hits
        if hit.is_course_like and _root_url(hit.url) not in duplicate_roots
    ]

    course_list_found = any(hit.is_course_like for hit in hits)
    if course_list_found:
        recommended_depth = 1
    elif hits:
        recommended_depth = 2
    else:
        recommended_depth = 3

    return SearchResult(
        source_url=request.source_url,
        source_domain=request.source_domain,
        university_names=request.university_names,
        hits=hits,
        root_seed_urls=filtered_roots,
        detailed_seed_urls=detailed_seed_urls,
        course_list_found=course_list_found,
        recommended_depth=recommended_depth,
        duplicate_root_urls=sorted(duplicate_roots),
        errors=errors,
    )


def search_seeds(item: ObserveStackItem, api: BraveSearchAPI | None = None) -> SearchResult:
    return _search_seeds_sync(item=item, api=api)


def _search_seeds_sync(item: ObserveStackItem, api: BraveSearchAPI | None = None) -> SearchResult:
    request = build_search_request(item)
    client_api = api or BraveSearchAPI()
    queries = _build_domain_discovery_queries(request)
    api_usage_count = 0
    first_search_count = 0
    internal_link_extracted_count = 0
    fallback_executed = False

    hits_by_url: dict[str, SearchHit] = {}
    errors: list[str] = []

    if not client_api.enabled:
        errors.append("BRAVE_API_KEY is not set. search is skipped.")
        return _build_result(request, [], errors)

    for query in queries:
        try:
            api_usage_count += 1
            rows = client_api.search(query=query, num_results=8)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"query={query}: {type(exc).__name__}: {exc}")
            continue

        first_search_count += len(rows)

        for row in rows:
            url = row["url"]
            score = _course_like_score(url=url, title=row["title"], snippet=row["snippet"], query=query)
            hit = SearchHit(
                query=query,
                url=url,
                title=row["title"],
                snippet=row["snippet"],
                score=score,
                is_course_like=score >= 4.0,
            )
            current = hits_by_url.get(url)
            if current is None or hit.score > current.score:
                hits_by_url[url] = hit

    hits = sorted(hits_by_url.values(), key=lambda h: h.score, reverse=True)
    hits = _enrich_hits_with_probe(hits, errors)

    # 1) 公式ドメイン推定
    official_domains = _select_official_domains(hits, request.university_names)

    # 2) 公式ドメイン内の内部リンク探索（courses/programmes っぽいリンク抽出）
    internal_links = _discover_internal_links_from_official_hits(hits, official_domains, errors)
    internal_link_extracted_count = len(internal_links)
    if internal_links:
        try:
            asyncio.get_running_loop()
            internal_hits = _probe_urls_sync(internal_links, errors)
        except RuntimeError:
            internal_hits = asyncio.run(_probe_urls_async(internal_links, errors))
        for ihit in internal_hits:
            prev = hits_by_url.get(ihit.url)
            if prev is None or ihit.score > prev.score:
                hits_by_url[ihit.url] = ihit

    # 2.5) コース一覧が取れなければ条件付きで再検索
    merged_hits = sorted(hits_by_url.values(), key=lambda h: h.score, reverse=True)
    if not any(hit.course_list_detected or hit.is_course_like for hit in merged_hits):
        fallback_queries = _build_course_fallback_queries(official_domains, request)
        fallback_executed = bool(fallback_queries)
        for query in fallback_queries:
            try:
                api_usage_count += 1
                rows = client_api.search(query=query, num_results=6)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"fallback_query={query}: {type(exc).__name__}: {exc}")
                continue

            for row in rows:
                url = row["url"]
                score = _course_like_score(url=url, title=row["title"], snippet=row["snippet"], query=query)
                hit = SearchHit(
                    query=query,
                    url=url,
                    title=row["title"],
                    snippet=row["snippet"],
                    score=score,
                    is_course_like=score >= 4.0,
                )
                current = hits_by_url.get(url)
                if current is None or hit.score > current.score:
                    hits_by_url[url] = hit

        merged_hits = sorted(hits_by_url.values(), key=lambda h: h.score, reverse=True)
        merged_hits = _enrich_hits_with_probe(merged_hits, errors)

    hits = merged_hits
    result = _build_result(request, hits, errors)

    search_log_store = SearchLogStore.from_env()
    if search_log_store is not None:
        try:
            search_log_store.init_db()
            search_log_store.insert_run_log(
                SearchRunLogRecord(
                    source_url=request.source_url,
                    source_domain=request.source_domain,
                    api_type=client_api.api_type,
                    first_search_count=first_search_count,
                    internal_link_extracted_count=internal_link_extracted_count,
                    fallback_executed=fallback_executed,
                    api_usage_count=api_usage_count,
                    run_id=item.observe_run_id,
                    source_stage="seed_searcher",
                )
            )
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"search_log_write_failed: {type(exc).__name__}: {exc}")
        finally:
            search_log_store.close()

    return result


def to_seed_discovery(result: SearchResult) -> SeedDiscovery:
    seed_urls = list(result.detailed_seed_urls)
    for root in result.root_seed_urls:
        if root not in seed_urls:
            seed_urls.append(root)

    discovery = SeedDiscovery(
        domain_url=result.source_url,
        seed_urls=seed_urls,
        depth=result.recommended_depth,
    )
    for hit in result.hits:
        discovery.add_seed_candidate(hit.url, hit.score)
    return discovery


def handle_observe_item(item: ObserveStackItem) -> SearchResult:
    result = search_seeds(item)
    print(
        "[OBSERVE_SEARCHER] "
        f"source={result.source_url} "
        f"universities={len(result.university_names)} "
        f"hits={len(result.hits)} "
        f"roots={len(result.root_seed_urls)} "
        f"course_like={result.course_list_found} "
        f"depth={result.recommended_depth} "
        f"dupes={len(result.duplicate_root_urls)}"
    )
    if result.errors:
        print(f"[OBSERVE_SEARCHER] errors={'; '.join(result.errors)}")
    return result