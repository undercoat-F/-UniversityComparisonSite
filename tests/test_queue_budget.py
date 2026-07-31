#!/usr/bin/env python
# -*- coding: utf-8 -*-

import unittest

from crawler.crawlworker import _should_log_tag_class_counts
from dataclass.dataclass import QueueBudget, SiteState


class TestQueueBudget(unittest.TestCase):
    def test_enqueue_stops_at_limit_and_releases_on_pop(self):
        budget = QueueBudget(limit=2)
        site = SiteState(domain="example.edu", start_urls=[], max_depth=2, enqueue_budget=budget)

        self.assertTrue(site.enqueue("https://example.edu/a", depth=0))
        self.assertTrue(site.enqueue("https://example.edu/b", depth=0))
        self.assertFalse(site.enqueue("https://example.edu/c", depth=0))
        self.assertEqual(budget.pending_count, 2)

        task = site.pop_next_task()
        self.assertIsNotNone(task)
        self.assertEqual(budget.pending_count, 1)

        self.assertTrue(site.enqueue("https://example.edu/c", depth=0))
        self.assertEqual(budget.pending_count, 2)

    def test_tag_class_count_logging_stops_after_domain_limit(self):
        site = SiteState(domain="example.edu", start_urls=[], max_depth=2)

        allowed = []
        for index in range(1, 23):
            url = f"https://example.edu/p/{index}"
            allowed.append(_should_log_tag_class_counts(site, url))

        self.assertEqual(sum(1 for item in allowed if item), 20)
        self.assertEqual(allowed[-1], False)
        self.assertEqual(allowed[-2], False)


if __name__ == "__main__":
    unittest.main(verbosity=2)