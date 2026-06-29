CREATE TABLE IF NOT EXISTS seed_search_runs (
  id BIGSERIAL PRIMARY KEY,
  run_id BIGINT,
  source_stage TEXT NOT NULL DEFAULT 'seed_searcher',
  source_url TEXT NOT NULL,
  source_domain TEXT NOT NULL,
  api_type TEXT NOT NULL,
  first_search_count INTEGER NOT NULL DEFAULT 0 CHECK(first_search_count >= 0),
  internal_link_extracted_count INTEGER NOT NULL DEFAULT 0 CHECK(internal_link_extracted_count >= 0),
  fallback_executed BOOLEAN NOT NULL DEFAULT FALSE,
  api_usage_count INTEGER NOT NULL DEFAULT 0 CHECK(api_usage_count >= 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE seed_search_runs
  ADD COLUMN IF NOT EXISTS run_id BIGINT;

ALTER TABLE seed_search_runs
  ADD COLUMN IF NOT EXISTS source_stage TEXT NOT NULL DEFAULT 'seed_searcher';

CREATE INDEX IF NOT EXISTS idx_seed_search_runs_source_domain
  ON seed_search_runs(source_domain);

CREATE INDEX IF NOT EXISTS idx_seed_search_runs_run_id
  ON seed_search_runs(run_id);

CREATE INDEX IF NOT EXISTS idx_seed_search_runs_created_at
  ON seed_search_runs(created_at DESC);
