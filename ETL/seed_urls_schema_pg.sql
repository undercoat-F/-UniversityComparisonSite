-- PostgreSQL 用 seed_urls テーブルスキーマ

CREATE TABLE IF NOT EXISTS seed_urls (
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

CREATE INDEX IF NOT EXISTS idx_seed_urls_enabled ON seed_urls(enabled);
CREATE INDEX IF NOT EXISTS idx_seed_urls_domain ON seed_urls(domain);
