#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_seed_transformer.py
seed_transformer のユニットテスト
- domain 単位 depth 決定
- seed_adder 形式 [(root_url, depth)] への変換
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dataclass.dataclass import SearchHit, SeedTransformInput
from observer.seed_transformer import build_seed_discovery, to_adder_targets, to_adder_targets_batch


def _make_item(
    source_url: str,
    source_domain: str,
    recommended_depth: int,
    course_list_found: bool,
    root_seed_urls: list[str],
    detailed_seed_urls: list[str],
    hits: list[SearchHit] | None = None,
) -> SeedTransformInput:
    return SeedTransformInput(
        source_url=source_url,
        source_domain=source_domain,
        university_names=["Sample University"],
        hits=hits or [],
        root_seed_urls=root_seed_urls,
        detailed_seed_urls=detailed_seed_urls,
        course_list_found=course_list_found,
        recommended_depth=recommended_depth,
        duplicate_root_urls=[],
    )


class TestSeedTransformer(unittest.TestCase):
    def test_to_adder_targets_single_item(self):
        item = _make_item(
            source_url="https://www.sample.ac.uk/about",
            source_domain="www.sample.ac.uk",
            recommended_depth=1,
            course_list_found=True,
            root_seed_urls=["https://www.sample.ac.uk"],
            detailed_seed_urls=["https://www.sample.ac.uk/courses/ug"],
        )

        targets = to_adder_targets(item)
        self.assertIn(("https://www.sample.ac.uk", 1), targets)
        self.assertEqual(len(targets), 1)

    def test_to_adder_targets_batch_domain_depth_unified(self):
        item_a = _make_item(
            source_url="https://www.example.edu/observer-a",
            source_domain="www.example.edu",
            recommended_depth=3,
            course_list_found=False,
            root_seed_urls=["https://www.example.edu"],
            detailed_seed_urls=[],
            hits=[],
        )
        item_b = _make_item(
            source_url="https://www.example.edu/observer-b",
            source_domain="www.example.edu",
            recommended_depth=1,
            course_list_found=True,
            root_seed_urls=["https://www.example.edu"],
            detailed_seed_urls=["https://www.example.edu/programmes/pg"],
            hits=[
                SearchHit(
                    query="q",
                    url="https://www.example.edu/programmes/pg",
                    title="Programmes",
                    snippet="",
                    score=8.0,
                    is_course_like=True,
                    course_list_detected=True,
                )
            ],
        )

        targets = to_adder_targets_batch([item_a, item_b])
        self.assertIn(("https://www.example.edu", 1), targets)
        self.assertEqual(len(targets), 1)

    def test_build_seed_discovery_normalizes_to_root_urls(self):
        item = _make_item(
            source_url="https://uni.example.com/observer",
            source_domain="uni.example.com",
            recommended_depth=2,
            course_list_found=False,
            root_seed_urls=[],
            detailed_seed_urls=[
                "https://uni.example.com/courses/a",
                "https://uni.example.com/courses/b",
            ],
        )

        discovery = build_seed_discovery(item)
        self.assertEqual(discovery.seed_urls, ["https://uni.example.com"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
