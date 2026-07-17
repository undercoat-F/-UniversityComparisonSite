from __future__ import annotations

import argparse
from dataclasses import dataclass

from dataclass.dataclass import SeedTransformInput
from observer.observe_log import ObserveLogStore, ObserveRunLogRecord
from observer.observe_supervisor import OBSERVE_SOURCE_URLS, dispatch_to_searcher, run_supervisor
from observer.seed_adder import promote_high_quality_targets_from_stage
from observer.seed_searcher import handle_observe_item


@dataclass
class ObserverPipelineSummary:
	observed_urls: int
	queued_items: int
	dispatched_items: int
	transformed_items: int
	added_targets: int
	promoted_targets: int
	observe_errors: int


def run_observer_pipeline(
	*,
	source_urls: list[str] | None = None,
	observe_run_id: int | None = None,
	promote_min_hit_count: int = 8,
	promote_max_error_count: int = 3,
	promote_max_depth: int = 2,
) -> ObserverPipelineSummary:
	source_count = len(source_urls or OBSERVE_SOURCE_URLS)
	observe_log_store = ObserveLogStore.from_env()
	run_log_id: int | None = None
	if observe_log_store is not None:
		try:
			observe_log_store.init_db()
			run_log_id = observe_log_store.create_run(
				ObserveRunLogRecord(
					external_run_id=observe_run_id,
					source_count=source_count,
				)
			)
		except Exception as exc:  # noqa: BLE001
			print(f"[OBSERVE_LOG_WARN] init/create failed: {type(exc).__name__}: {exc}")
			try:
				observe_log_store.close()
			except Exception:  # noqa: BLE001
				pass
			observe_log_store = None
			run_log_id = None

	observe_results = []
	queue = None
	transformed_items: list[SeedTransformInput] = []
	dispatched_items = 0
	added_targets = 0
	promoted_targets = 0
	pipeline_error: Exception | None = None
	pipeline_traceback = None

	try:
		observe_results, queue = run_supervisor(source_urls=source_urls, observe_run_id=observe_run_id)

		def _searcher_handler(item) -> None:
			result = handle_observe_item(item)
			transformed_items.append(result)
			if observe_log_store is not None and run_log_id is not None:
				try:
					observe_log_store.insert_result(
						run_log_id,
						external_run_id=observe_run_id,
						source_stage=result.source_stage,
						item=item,
						result=result,
						request_log_count=len(item.request_logs),
					)
				except Exception as exc:  # noqa: BLE001
					print(f"[OBSERVE_LOG_WARN] insert_result failed: {type(exc).__name__}: {exc}")

		dispatched_items = dispatch_to_searcher(queue, _searcher_handler)
		if run_log_id is None:
			raise RuntimeError(
				"Observe log run_id is unavailable. Quality-gated promotion requires OBSERVE_LOG_* DSN configuration."
			)

		promotion = promote_high_quality_targets_from_stage(
			observe_log_run_id=run_log_id,
			external_run_id=observe_run_id,
			min_hit_count=promote_min_hit_count,
			max_error_count=promote_max_error_count,
			max_recommended_depth=promote_max_depth,
		)
		promoted_targets = promotion.promoted_targets
		added_targets = promoted_targets
		print(
			"[SEED_PROMOTION] "
			f"stage_source={promotion.stage_source} "
			f"target_source={promotion.target_source} "
			f"scanned={promotion.scanned_rows} "
			f"accepted={promotion.accepted_rows} "
			f"promoted={promotion.promoted_targets}"
		)
	except Exception as exc:  # noqa: BLE001
		pipeline_error = exc
		pipeline_traceback = exc.__traceback__
	finally:
		if observe_log_store is not None and run_log_id is not None:
			status = "failed" if pipeline_error is not None else "completed"
			try:
				observe_log_store.finish_run(
					run_log_id,
					ObserveRunLogRecord(
						external_run_id=observe_run_id,
						source_count=source_count,
						observed_count=len(observe_results),
						queued_count=len(observe_results),
						dispatched_count=dispatched_items,
						transformed_count=len(transformed_items),
						added_targets_count=added_targets,
						error_count=sum(r.error_count for r in observe_results),
						status=status,
					),
				)
			except Exception as exc:  # noqa: BLE001
				print(f"[OBSERVE_LOG_WARN] finish_run failed: {type(exc).__name__}: {exc}")
			finally:
				observe_log_store.close()

	if pipeline_error is not None:
		raise pipeline_error.with_traceback(pipeline_traceback)

	return ObserverPipelineSummary(
		observed_urls=len(observe_results),
		queued_items=dispatched_items,
		dispatched_items=dispatched_items,
		transformed_items=len(transformed_items),
		added_targets=added_targets,
		promoted_targets=promoted_targets,
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
		"--promote-min-hit-count",
		type=int,
		default=8,
		help="Minimum hit_count required for promotion.",
	)
	parser.add_argument(
		"--promote-max-error-count",
		type=int,
		default=3,
		help="Maximum error_count allowed for promotion.",
	)
	parser.add_argument(
		"--promote-max-depth",
		type=int,
		default=2,
		help="Maximum recommended_depth allowed for promotion.",
	)
	return parser


def main() -> None:
	args = _build_arg_parser().parse_args()
	summary = run_observer_pipeline(
		source_urls=args.url,
		observe_run_id=args.observe_run_id,
		promote_min_hit_count=args.promote_min_hit_count,
		promote_max_error_count=args.promote_max_error_count,
		promote_max_depth=args.promote_max_depth,
	)
	print(
		"[OBSERVER_PIPELINE] "
		f"observed={summary.observed_urls} "
		f"queued={summary.queued_items} "
		f"dispatched={summary.dispatched_items} "
		f"transformed={summary.transformed_items} "
		f"added_targets={summary.added_targets} "
		f"promoted_targets={summary.promoted_targets} "
		f"observe_errors={summary.observe_errors}"
	)


if __name__ == "__main__":
	print("[OBSERVER_PIPELINE] Starting observer pipeline...")
	main()
