CREATE SCHEMA IF NOT EXISTS observer;

CREATE TABLE IF NOT EXISTS "observer"."seed_urls" (
  id SERIAL PRIMARY KEY,
  country VARCHAR(50) NOT NULL,
  domain VARCHAR(255) NOT NULL,
  root_url VARCHAR(2048) NOT NULL,
  depth INTEGER NOT NULL CHECK(depth >= 0),
  enabled SMALLINT NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(domain, root_url)
);

CREATE INDEX IF NOT EXISTS idx_seed_urls_enabled ON "observer"."seed_urls"(enabled);
CREATE INDEX IF NOT EXISTS idx_seed_urls_domain ON "observer"."seed_urls"(domain);

CREATE TABLE IF NOT EXISTS "observer"."seed_search_runs" (
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

ALTER TABLE "observer"."seed_search_runs"
  ADD COLUMN IF NOT EXISTS run_id BIGINT;

ALTER TABLE "observer"."seed_search_runs"
  ADD COLUMN IF NOT EXISTS source_stage TEXT NOT NULL DEFAULT 'seed_searcher';

CREATE INDEX IF NOT EXISTS idx_seed_search_runs_source_domain
  ON "observer"."seed_search_runs"(source_domain);

CREATE INDEX IF NOT EXISTS idx_seed_search_runs_run_id
  ON "observer"."seed_search_runs"(run_id);

CREATE INDEX IF NOT EXISTS idx_seed_search_runs_created_at
  ON "observer"."seed_search_runs"(created_at DESC);

CREATE TABLE IF NOT EXISTS "observer"."seed_observe_runs" (
  id BIGSERIAL PRIMARY KEY,
  external_run_id BIGINT,
  source_count INTEGER NOT NULL DEFAULT 0 CHECK(source_count >= 0),
  observed_count INTEGER NOT NULL DEFAULT 0 CHECK(observed_count >= 0),
  queued_count INTEGER NOT NULL DEFAULT 0 CHECK(queued_count >= 0),
  dispatched_count INTEGER NOT NULL DEFAULT 0 CHECK(dispatched_count >= 0),
  transformed_count INTEGER NOT NULL DEFAULT 0 CHECK(transformed_count >= 0),
  added_targets_count INTEGER NOT NULL DEFAULT 0 CHECK(added_targets_count >= 0),
  error_count INTEGER NOT NULL DEFAULT 0 CHECK(error_count >= 0),
  status TEXT NOT NULL DEFAULT 'running' CHECK(status IN ('running', 'completed', 'failed')),
  notes TEXT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_seed_observe_runs_external_run_id
  ON "observer"."seed_observe_runs"(external_run_id);

CREATE INDEX IF NOT EXISTS idx_seed_observe_runs_started_at
  ON "observer"."seed_observe_runs"(started_at DESC);

CREATE TABLE IF NOT EXISTS "observer"."seed_observe_results" (
  id BIGSERIAL PRIMARY KEY,
  run_id BIGINT NOT NULL REFERENCES "observer"."seed_observe_runs"(id) ON DELETE CASCADE,
  external_run_id BIGINT,
  source_stage TEXT NOT NULL DEFAULT 'seed_searcher',
  source_url TEXT NOT NULL,
  source_domain TEXT NOT NULL,
  source_page_type TEXT NOT NULL,
  page_flags JSONB NOT NULL DEFAULT '{}'::jsonb,
  candidate_lines JSONB NOT NULL DEFAULT '[]'::jsonb,
  request_log_count INTEGER NOT NULL DEFAULT 0 CHECK(request_log_count >= 0),
  university_names JSONB NOT NULL DEFAULT '[]'::jsonb,
  hit_count INTEGER NOT NULL DEFAULT 0 CHECK(hit_count >= 0),
  hits JSONB NOT NULL DEFAULT '[]'::jsonb,
  root_seed_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
  detailed_seed_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
  course_list_found BOOLEAN NOT NULL DEFAULT FALSE,
  recommended_depth INTEGER NOT NULL DEFAULT 3 CHECK(recommended_depth >= 0),
  duplicate_root_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
  errors JSONB NOT NULL DEFAULT '[]'::jsonb,
  error_count INTEGER NOT NULL DEFAULT 0 CHECK(error_count >= 0),
  api_type TEXT NOT NULL DEFAULT 'brave',
  first_search_count INTEGER NOT NULL DEFAULT 0 CHECK(first_search_count >= 0),
  internal_link_extracted_count INTEGER NOT NULL DEFAULT 0 CHECK(internal_link_extracted_count >= 0),
  fallback_executed BOOLEAN NOT NULL DEFAULT FALSE,
  api_usage_count INTEGER NOT NULL DEFAULT 0 CHECK(api_usage_count >= 0),
  search_queries JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE "observer"."seed_observe_results"
  ADD COLUMN IF NOT EXISTS search_queries JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE INDEX IF NOT EXISTS idx_seed_observe_results_run_id
  ON "observer"."seed_observe_results"(run_id);

CREATE INDEX IF NOT EXISTS idx_seed_observe_results_source_domain
  ON "observer"."seed_observe_results"(source_domain);

CREATE INDEX IF NOT EXISTS idx_seed_observe_results_created_at
  ON "observer"."seed_observe_results"(created_at DESC);
