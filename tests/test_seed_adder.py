#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_seed_adder.py
seed_adder のユニットテスト
- transformer 出力を ETL 側 upsert_targets へ渡す
"""

import os
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "psycopg2" not in sys.modules:
    sys.modules["psycopg2"] = types.SimpleNamespace(Error=Exception)
if "dotenv" not in sys.modules:
    sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda *a, **k: None)

from dataclass.dataclass import SeedTransformInput
from observer.seed_adder import add_seed_targets


class TestSeedAdder(unittest.TestCase):
    def test_add_seed_targets_calls_upsert_targets(self):
        with (
            patch("observer.seed_adder.to_adder_targets_batch", return_value=[("https://www.example.edu", 1)]) as m_transform,
            patch("observer.seed_adder.init_seed_db.upsert_targets") as m_upsert,
        ):
            count = add_seed_targets([SeedTransformInput(
                source_url="https://www.example.edu",
                source_domain="www.example.edu",
                university_names=[],
                hits=[],
                root_seed_urls=[],
                detailed_seed_urls=[],
                course_list_found=False,
                recommended_depth=3,
                duplicate_root_urls=[],
            )])

        self.assertEqual(count, 1)
        m_transform.assert_called_once()
        m_upsert.assert_called_once_with([("https://www.example.edu", 1)])

    def test_add_seed_targets_skips_upsert_when_empty(self):
        with (
            patch("observer.seed_adder.to_adder_targets_batch", return_value=[]) as m_transform,
            patch("observer.seed_adder.init_seed_db.upsert_targets") as m_upsert,
        ):
            count = add_seed_targets([])

        self.assertEqual(count, 0)
        m_transform.assert_called_once_with([])
        m_upsert.assert_not_called()

    def test_add_seed_targets_can_init_schema(self):
        with (
            patch("observer.seed_adder.to_adder_targets_batch", return_value=[("https://www.example.edu", 2)]),
            patch("observer.seed_adder.init_seed_db.init_db") as m_init,
            patch("observer.seed_adder.init_seed_db.upsert_targets") as m_upsert,
        ):
            count = add_seed_targets([], ensure_schema=True)

        self.assertEqual(count, 1)
        m_init.assert_called_once()
        m_upsert.assert_called_once_with([("https://www.example.edu", 2)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
