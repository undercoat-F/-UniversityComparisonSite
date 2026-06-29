from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Literal, Optional
from urllib.robotparser import RobotFileParser
from enum import Enum, auto

@dataclass
class URLTask:
    url: str
    depth: int
    discovered_from: str = ""
    retry_count: int = 0
    status: str = "pending"
    queued_at: float = field(default_factory=time.time)


@dataclass
class CrawlAttempt:
    url: str
    ok: bool
    task_depth: int = 0
    status_code: Optional[int] = None
    used_fallback: bool = False
    error: str = ""
    discovered_urls: int = 0
    queued_urls: list[str] = field(default_factory=list)
    extracted_records: list[dict[str, Any]] = field(default_factory=list)
    connection_log: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class FetchResult:
    html_text: str
    status_code: Optional[int]
    used_fallback: bool
    connection_log: list[dict[str, Any]]


@dataclass
class SiteState:
    domain: str
    start_urls: list[str]
    run_id: Optional[int] = None
    queue_logger: Optional[Any] = None
    crawl_delay: float = 0.0
    last_access: float = 0.0
    user_agent: str = "*"
    status: str = "active"
    max_depth: int = 1
    log: dict = field(
        default_factory=lambda: {
            "success_count": 0,
            "error_count": 0,
            "total_time": 0.0,
            "fallback_count": 0,
        }
    )
    sitemap: Optional[Any] = None
    domain_semaphore_limit: int = 1
    robotstxt: Optional[str] = None

    queue: deque[URLTask] = field(default_factory=deque)
    visited: set[str] = field(default_factory=set)
    queued: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)
    in_progress_urls: set[str] = field(default_factory=set)
    extracted_links_by_url: dict[str, list[str]] = field(default_factory=dict)
    crawl_attempts: list[CrawlAttempt] = field(default_factory=list)
    extracted_records: list[dict[str, Any]] = field(default_factory=list)
    robots_parser: Optional[RobotFileParser] = None
    robots_ready: bool = False
    sitemap_urls: list[str] = field(default_factory=list)
    sitemap_candidates: list[str] = field(default_factory=list)
    sitemap_attempted: bool = False

    extraction_drop_stats: dict[str, int] = field(
        default_factory=lambda: {
            "degree_line_hits": 0,
            "dropped_fee_context": 0,
            "dropped_non_numeric": 0,
            "kept_with_price": 0,
            "kept_without_price": 0,
        }
    )

    def __post_init__(self) -> None:
        for url in self.start_urls:
            self.enqueue(url=url, depth=0)

    def post_init(self) -> None:
        self.__post_init__()

    @property
    def success_count(self) -> int:
        return int(self.log["success_count"])

    @property
    def error_count(self) -> int:
        return int(self.log["error_count"])

    @property
    def total_time(self) -> float:
        return float(self.log["total_time"])

    @property
    def fallback_count(self) -> int:
        return int(self.log["fallback_count"])

    def has_pending(self) -> bool:
        return bool(self.queue)

    def can_fetch(self) -> bool:
        return (time.time() - self.last_access) >= self.crawl_delay

    def seconds_until_ready(self) -> float:
        return max(0.0, self.crawl_delay - (time.time() - self.last_access))

    def mark_access(self) -> None:
        self.last_access = time.time()

    def enqueue(self, url: str, depth: int, discovered_from: str = "") -> bool:
        if url in self.visited or url in self.queued or depth > self.max_depth:
            return False
        self.queue.append(URLTask(url=url, depth=depth, discovered_from=discovered_from))
        self.queued.add(url)

        if self.queue_logger is not None and self.run_id is not None:
            try:
                source = "link"
                parent_for_log = discovered_from
                if discovered_from == "sitemap":
                    source = "sitemap"
                    parent_for_log = ""
                elif discovered_from == "manual":
                    source = "manual"
                    parent_for_log = ""

                self.queue_logger.upsert_queue_state(
                    run_id=self.run_id,
                    url=url,
                    parent_url=parent_for_log,
                    domain=self.domain,
                    depth=depth,
                    status="pending",
                    discovered_from=discovered_from,
                )
                if parent_for_log:
                    self.queue_logger.add_edge(
                        run_id=self.run_id,
                        parent_url=parent_for_log,
                        child_url=url,
                        parent_domain=self.domain,
                        child_domain=self.domain,
                        depth=depth,
                        source=source,
                    )
            except Exception:
                pass

        return True

    def pop_next_task(self) -> Optional[URLTask]:
        if not self.queue:
            return None
        task = self.queue.popleft()
        self.queued.discard(task.url)
        return task

    def set_domain_semaphore_limit(self, limit: int) -> None:
        self.domain_semaphore_limit = limit

    def start_task(self, task: URLTask) -> None:
        self.mark_access()
        self.visited.add(task.url)
        self.in_progress_urls.add(task.url)

    def finish_task(self, task_url: str) -> None:
        self.in_progress_urls.discard(task_url)

    def record_links(self, source_url: str, links: list[str]) -> None:
        self.extracted_links_by_url[source_url] = links

    def record_attempt(self, attempt: CrawlAttempt, elapsed_sec: float) -> None:
        self.crawl_attempts.append(attempt)
        self.log["total_time"] += elapsed_sec
        if attempt.ok:
            self.log["success_count"] += 1
        else:
            self.log["error_count"] += 1
        if attempt.used_fallback:
            self.log["fallback_count"] += 1

    def add_extracted_record(self, record: dict[str, Any]) -> None:
        self.extracted_records.append(record)

@dataclass
class SeedDiscovery:
    domain_url: str
    seed_urls: list[str] = field(default_factory=list)
    depth: Optional[int] = 2

    seed_candidates: dict[str, float] = field(default_factory=dict)

    source_site: str | None = None
    university_name: str | None = None
    requests_log: list[dict[str, Any]] = field(default_factory=list)

    def add_log(
        self,
        url: str,
        status_code: Optional[int],
        error: Optional[str] = None,
        step: Literal["observe", "search", "extract", "transform", "add"] = "observe",
    ) -> None:
        self.requests_log.append({
            "url": url,
            "status_code": status_code,
            "error": error,
            "timestamp": time.time(),
            "step": step  # This can be set based on the context of the log entry
        })

    def add_seed_candidate(self, url: str, score: float) -> None:
        current = self.seed_candidates.get(url)
        if current is None or score > current:
            self.seed_candidates[url] = score


@dataclass
class SearchRequest:
    source_url: str
    source_domain: str
    university_names: list[str]
    content_type: str
    candidate_lines: list[str] = field(default_factory=list)


@dataclass
class SearchHit:
    query: str
    url: str
    title: str
    snippet: str
    score: float
    is_course_like: bool
    search_form_detected: bool = False
    course_list_detected: bool = False


@dataclass
class SearchResult:
    source_url: str
    source_domain: str
    university_names: list[str]
    hits: list[SearchHit]
    root_seed_urls: list[str]
    detailed_seed_urls: list[str]
    course_list_found: bool
    recommended_depth: int
    duplicate_root_urls: list[str]
    errors: list[str] = field(default_factory=list)

# 監視ページの特徴を表すクラス
class ContentType(Enum):
    PDF = "pdf"
    HTML = "html"
    IMAGE = "image"
    JSON = "json"
    OTHER = "other"

@dataclass #監視サイトの分析結果を保持するクラス
class PageAnalysis:
    content_type: ContentType = ContentType.OTHER

    table_list: bool = False#TABLEタグページ,表形式PDF
    search_form: bool = False#大学検索フォーム
    profile: bool = False#大学検索詳細
    text: bool = False#テキスト中心のページ,テキスト形式PDF

    candidate_lines: list[str] = field(default_factory=list)
    #タグ集計結果を持つ辞書を追加してもよい
    extracted_universitynamelist: list[str] = field(default_factory=list)

    response : Optional[Any] = None

@dataclass
class SearchRunLogRecord:
    source_url: str
    source_domain: str
    api_type: str
    first_search_count: int
    internal_link_extracted_count: int
    fallback_executed: bool
    api_usage_count: int
    run_id: Optional[int] = None
    source_stage: str = "seed_searcher"