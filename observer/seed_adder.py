from __future__ import annotations

from dataclass.dataclass import SeedTransformInput
from observer.seed_transformer import to_adder_targets_batch

try:
    from ETL import init_seed_db as init_seed_db
except Exception:  # pragma: no cover
    init_seed_db = None


def add_seed_targets(items: list[SeedTransformInput], *, ensure_schema: bool = False) -> int:
    """Transform items to (root_url, depth) targets and upsert into ETL seed_urls DB.

    Returns:
        Number of targets passed to upsert.
    """
    targets = to_adder_targets_batch(items)
    if not targets:
        return 0

    db_module = init_seed_db
    if db_module is None:
        from ETL import init_seed_db as db_module

    if ensure_schema:
        db_module.init_db()

    db_module.upsert_targets(targets)
    return len(targets)
