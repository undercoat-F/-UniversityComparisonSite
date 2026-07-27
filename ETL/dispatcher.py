from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlparse

import httpx

from crawler.crawlworker import DEFAULT_HEADERS, seed_sitemap_candidates, worker
from dataclass.dataclass import SiteState
from ETL.queue_log import QueueLogStore


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


async def _seed_sitemaps_with_limits(sites: list[SiteState]) -> tuple[int, int]:
    seeding_concurrency = _env_int("ETL_SITEMAP_SEED_CONCURRENCY", 12)
    per_site_timeout = _env_int("ETL_SITEMAP_SEED_SITE_TIMEOUT_SEC", 90)
    progress_every = _env_int("ETL_SITEMAP_SEED_PROGRESS_EVERY", 20)

    sem = asyncio.Semaphore(seeding_concurrency)

    async def _one(site: SiteState):
        async with sem:
            try:
                await asyncio.wait_for(seed_sitemap_candidates(site), timeout=per_site_timeout)
                return site.domain, None
            except Exception as exc:  # noqa: BLE001
                return site.domain, exc

    tasks = [asyncio.create_task(_one(site)) for site in sites]
    completed = 0
    failed = 0
    by_domain = {site.domain: site for site in sites}

    for task in asyncio.as_completed(tasks):
        domain, exc = await task
        completed += 1
        if exc is not None:
            failed += 1
            site = by_domain.get(domain)
            msg = f"sitemap_seed_failed domain={domain}: {type(exc).__name__}: {exc}"
            if site is not None:
                site.errors.append(msg)
            print(f"[DISPATCHER][WARN] {msg}", flush=True)

        if completed % progress_every == 0 or completed == len(tasks):
            print(
                f"[DISPATCHER] sitemap seeding progress done={completed}/{len(tasks)} failed={failed}",
                flush=True,
            )

    seeded_total = sum(len(site.sitemap_candidates) for site in sites)
    return seeded_total, failed

def build_site_states(targets: Iterable[tuple[str, int]]) -> list[SiteState]:
    grouped: dict[str, list[tuple[str, int]]] = {}
    for url, depth in targets:
        domain = urlparse(url).netloc
        grouped.setdefault(domain, []).append((url, depth))

    sites: list[SiteState] = []
    for domain, entries in grouped.items():
        start_urls = [url for url, _ in entries]
        max_depth = max(depth for _, depth in entries)
        sites.append(SiteState(domain=domain, start_urls=start_urls, max_depth=max_depth))
    return sites


def _active_sites(sites: list[SiteState]) -> list[SiteState]:
    return [site for site in sites if site.status == "active" and site.has_pending()]


async def run_dispatcher(
    targets: list[tuple[str, int]],
    *,
    max_active_sites: int = 4,
    timeout_sec: int = 30,
    progress_interval_sec: int = 10,
    queue_log_enabled: bool = True,
) -> list[SiteState]:
    """crawl-delay 中のサイトは待機し、ready な他ドメインを進める。"""
    #timeout_sec はサイト全体のタイムアウト（crawl-delay も含む）。最大待ち時間。
    sites = build_site_states(targets)
    if not sites:
        return sites

    queue_logger = None
    run_id = None
    queue_log_enabled = queue_log_enabled and _env_flag("QUEUE_LOG_ENABLED", True)
    if queue_log_enabled:
        queue_log_batch_size = int(os.getenv("QUEUE_LOG_BATCH_SIZE", "200"))
        queue_log_failures_only = os.getenv("QUEUE_LOG_FAILURES_ONLY", "1") not in {"0", "false", "False"}
        queue_log_pg_dsn = os.getenv("PARENT_DB_OWNER_CONNECTION", "").strip()
        if not queue_log_pg_dsn:
            required = ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD")
            if all((os.getenv(name, "").strip() for name in required)):
                host = os.getenv("DB_HOST", "").strip()
                dbname = os.getenv("DB_NAME", "").strip()
                user = os.getenv("DB_USER", "").strip()
                password = os.getenv("DB_PASSWORD", "").strip()
                port = os.getenv("DB_PORT", "5432").strip() or "5432"
                queue_log_pg_dsn = f"postgresql://{user}:{password}@{host}:{port}/{dbname}?sslmode=require"
        schema_path = os.getenv("QUEUE_LOG_SCHEMA_PATH", os.path.join("ETL", "queue_log_schema.sql"))

        if not queue_log_pg_dsn:
            print(
                "[QUEUE_LOG] disabled: PARENT_DB_OWNER_CONNECTION or DB_* is not set",
                flush=True,
            )
            queue_log_enabled = False

        if queue_log_enabled:
            queue_logger = QueueLogStore(
                db_path="",
                schema_path=schema_path,
                pg_dsn=queue_log_pg_dsn,
                batch_size=queue_log_batch_size,
                failures_only=queue_log_failures_only,
            )
            queue_logger.init_db()
            run_id = queue_logger.create_run(root_seed_count=len(targets), notes="dispatcher run")
            for site in sites:
                site.queue_logger = queue_logger
                site.run_id = run_id

    started_at = time.monotonic()
    last_progress_at = started_at

    print(
        f"[DISPATCHER] start sites={len(sites)} timeout={timeout_sec}s",
        flush=True,
    )

    async with httpx.AsyncClient(
        headers=DEFAULT_HEADERS,
        timeout=timeout_sec,
        follow_redirects=True,
    ) as session:
        run_status = "completed"
        run_notes = ""
        try:
            print("[DISPATCHER] seeding sitemap candidates...", flush=True)
            seeded_total, seeding_failed = await _seed_sitemaps_with_limits(sites)
            print(
                "[DISPATCHER] sitemap seeding done "
                f"candidates={seeded_total} failed={seeding_failed} elapsed={int(time.monotonic() - started_at)}s",
                flush=True,
            )

            while True:
                now = time.monotonic()
                if now - last_progress_at >= progress_interval_sec:
                    visited_total = sum(len(site.visited) for site in sites)
                    pending_total = sum(len(site.queue) for site in sites)
                    success_total = sum(site.success_count for site in sites)
                    error_total = sum(site.error_count for site in sites)
                    print(
                        "[PROGRESS] "
                        f"elapsed={int(now - started_at)}s "
                        f"visited_total={visited_total} "
                        f"pending_total={pending_total} "
                        f"success_total={success_total} "
                        f"error_total={error_total}",
                        flush=True,
                    )
                    last_progress_at = now

                active = _active_sites(sites)
                if not active:
                    break

                ready = [site for site in active if site.can_fetch()]
                if not ready:
                    sleep_for = min(site.seconds_until_ready() for site in active)
                    await asyncio.sleep(max(0.01, sleep_for))
                    continue

                ready = ready[:max_active_sites]
                await asyncio.gather(*(worker(site, session) for site in ready))
        except Exception as exc:
            run_status = "failed"
            run_notes = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            if queue_logger is not None and run_id is not None:
                queue_logger.finish_run(run_id=run_id, status=run_status, notes=run_notes)
                queue_logger.close()

    return sites