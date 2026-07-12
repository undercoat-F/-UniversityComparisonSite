from __future__ import annotations

from collections import defaultdict
from urllib.parse import urlparse

from dataclass.dataclass import SeedDiscovery, SeedTransformInput


def _root_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if not parsed.netloc:
        return ""
    scheme = parsed.scheme or "https"
    return f"{scheme}://{parsed.netloc}"


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def _decide_depth_for_domain(items: list[SeedTransformInput]) -> int:
    "個々の数字はdepthの推奨値を示す。1はコースリストが見つかった場合、2はコースに類似するページが見つかった場合、3はそれ以外の場合。"
    if not items:
        return 3

    has_course_list = any(
        item.course_list_found or any(hit.course_list_detected for hit in item.hits)
        for item in items
    )
    if has_course_list:
        return 1

    has_course_like = any(
        any(hit.is_course_like for hit in item.hits) or item.recommended_depth <= 2
        for item in items
    )
    if has_course_like:
        return 2

    return 3


def _collect_domain_root_urls(item: SeedTransformInput) -> list[str]:
    roots: list[str] = []

    for url in item.root_seed_urls:
        root = _root_url(url)
        if root and root not in roots:
            roots.append(root)

    for url in item.detailed_seed_urls:
        root = _root_url(url)
        if root and root not in roots:
            roots.append(root)

    source_root = _root_url(item.source_url)
    if source_root and source_root not in roots:
        roots.append(source_root)

    return roots


def build_seed_discovery(item: SeedTransformInput) -> SeedDiscovery:
    roots = _collect_domain_root_urls(item)
    discovery = SeedDiscovery(
        domain_url=_root_url(item.source_url) or item.source_url,
        seed_urls=roots,
        depth=item.recommended_depth,
    )
    discovery.source_site = item.source_domain
    discovery.university_name = item.university_names[0] if item.university_names else None

    for hit in item.hits:
        discovery.add_seed_candidate(hit.url, hit.score)

    return discovery


def build_seed_transform_input(item: SeedTransformInput) -> SeedTransformInput:
    return item


def to_adder_targets(item: SeedTransformInput) -> list[tuple[str, int]]:
    depth = _decide_depth_for_domain([item])
    return [(root, depth) for root in _collect_domain_root_urls(item)]


def to_adder_targets_batch(items: list[SeedTransformInput]) -> list[tuple[str, int]]:
    grouped: dict[str, list[SeedTransformInput]] = defaultdict(list)
    for item in items:
        domain = item.source_domain or _domain(item.source_url)
        if not domain:
            continue
        grouped[domain].append(item)

    targets: list[tuple[str, int]] = []
    seen: set[tuple[str, str]] = set()

    for domain, domain_items in grouped.items():
        depth = _decide_depth_for_domain(domain_items)
        for item in domain_items:
            for root in _collect_domain_root_urls(item):
                key = (domain, root)
                if key in seen:
                    continue
                seen.add(key)
                targets.append((root, depth))

    return targets