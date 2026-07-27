from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from observer import seed_observer
from observer.observe_supervisor import OBSERVE_SOURCE_URLS


@dataclass
class ConnectivityResult:
    url: str
    success: bool
    elapsed_sec: float
    extracted_name_count: int
    added_log_count: int
    error_count: int
    last_error: str | None


def _slice_new_logs(before_len: int) -> list[dict[str, Any]]:
    logs = seed_observer.Seed_State.requests_log
    return logs[before_len:]


def run_connectivity_check(source_urls: list[str]) -> list[ConnectivityResult]:
    results: list[ConnectivityResult] = []

    for url in source_urls:
        before_len = len(seed_observer.Seed_State.requests_log)
        started = time.perf_counter()
        page = seed_observer.observe_url(url)
        elapsed = time.perf_counter() - started

        new_logs = _slice_new_logs(before_len)
        error_logs = [item for item in new_logs if item.get("error")]
        last_error = error_logs[-1].get("error") if error_logs else None

        extracted_name_count = 0
        if page is not None:
            extracted_name_count = len(getattr(page, "extracted_universitynamelist", []) or [])

        success = page is not None
        results.append(
            ConnectivityResult(
                url=url,
                success=success,
                elapsed_sec=elapsed,
                extracted_name_count=extracted_name_count,
                added_log_count=len(new_logs),
                error_count=len(error_logs),
                last_error=last_error,
            )
        )

    return results


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Connectivity check for seed_observer.observe_url using "
            "observer.observe_supervisor.OBSERVE_SOURCE_URLS"
        )
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Override seed_observer.DEFAULT_TIMEOUT for this run (seconds)",
    )
    parser.add_argument(
        "--max-urls",
        type=int,
        default=None,
        help="Run only first N URLs from OBSERVE_SOURCE_URLS",
    )
    parser.add_argument(
        "--only",
        nargs="*",
        default=None,
        help="Run only URLs that contain all given substrings",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help="Optional path to save raw result JSON",
    )
    parser.add_argument(
        "--allow-failures",
        type=int,
        default=0,
        help="Allowed number of failed URLs before returning non-zero",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()

    source_urls = list(OBSERVE_SOURCE_URLS)
    if args.only:
        tokens = [token.lower() for token in args.only]
        source_urls = [
            url for url in source_urls if all(token in url.lower() for token in tokens)
        ]
    if args.max_urls is not None:
        source_urls = source_urls[: max(0, args.max_urls)]

    if not source_urls:
        print("[CONNECTIVITY] no target URLs")
        return 2

    if args.timeout is not None:
        seed_observer.DEFAULT_TIMEOUT = float(args.timeout)

    print(
        "[CONNECTIVITY] start "
        f"url_count={len(source_urls)} timeout={seed_observer.DEFAULT_TIMEOUT}"
    )

    results = run_connectivity_check(source_urls)

    fail_count = 0
    for item in results:
        status = "OK" if item.success else "FAIL"
        if not item.success:
            fail_count += 1
        print(
            "[CONNECTIVITY] "
            f"status={status} "
            f"elapsed={item.elapsed_sec:.2f}s "
            f"names={item.extracted_name_count} "
            f"errors={item.error_count} "
            f"url={item.url}"
        )
        if item.last_error:
            print(f"[CONNECTIVITY] last_error={item.last_error}")

    success_count = len(results) - fail_count
    print(
        "[CONNECTIVITY] summary "
        f"success={success_count} fail={fail_count} total={len(results)}"
    )

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps([asdict(item) for item in results], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[CONNECTIVITY] json_saved={out_path}")

    return 0 if fail_count <= max(0, args.allow_failures) else 1


if __name__ == "__main__":
    raise SystemExit(main())
