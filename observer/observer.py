from __future__ import annotations

import argparse
from dataclasses import dataclass

from dataclass.dataclass import SeedTransformInput
from observer.observe_supervisor import dispatch_to_searcher, run_supervisor


@dataclass
class ObserverPipelineSummary:
	observed_urls: int
	queued_items: int
	dispatched_items: int
	transformed_items: int
	added_targets: int
	observe_errors: int


def run_observer_pipeline(
	*,
	source_urls: list[str] | None = None,
	observe_run_id: int | None = None,
	ensure_schema: bool = False,
) -> ObserverPipelineSummary:
	from observer.seed_adder import add_seed_targets
	from observer.seed_searcher import handle_observe_item

	observe_results, queue = run_supervisor(source_urls=source_urls, observe_run_id=observe_run_id)
	transformed_items: list[SeedTransformInput] = []

	def _searcher_handler(item) -> None:
		transformed_items.append(handle_observe_item(item))

	dispatched_items = dispatch_to_searcher(queue, _searcher_handler)
	added_targets = add_seed_targets(transformed_items, ensure_schema=ensure_schema)

	return ObserverPipelineSummary(
		observed_urls=len(observe_results),
		queued_items=dispatched_items,
		dispatched_items=dispatched_items,
		transformed_items=len(transformed_items),
		added_targets=added_targets,
		observe_errors=sum(r.error_count for r in observe_results),
	)

#不明な関数　後で知る必要がある
def _build_arg_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description="Run observer -> supervisor -> searcher -> transformer -> adder")
	parser.add_argument(
		"--url",
		action="append",
		default=None,
		help="Observation source URL. Repeat to pass multiple URLs.",
	)
	parser.add_argument(
		"--observe-run-id",
		type=int,
		default=None,
		help="Optional observe run id to include in downstream logs.",
	)
	parser.add_argument(
		"--init-schema",
		action="store_true",
		help="Initialize seed DB schema before inserting targets.",
	)
	return parser


def main() -> None:
	args = _build_arg_parser().parse_args()
	summary = run_observer_pipeline(
		source_urls=args.url,
		observe_run_id=args.observe_run_id,
		ensure_schema=args.init_schema,
	)
	print(
		"[OBSERVER_PIPELINE] "
		f"observed={summary.observed_urls} "
		f"queued={summary.queued_items} "
		f"dispatched={summary.dispatched_items} "
		f"transformed={summary.transformed_items} "
		f"added_targets={summary.added_targets} "
		f"observe_errors={summary.observe_errors}"
	)


if __name__ == "__main__":
	main()
