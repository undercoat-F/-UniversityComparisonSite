CREATE TABLE IF NOT EXISTS seed_urls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  country TEXT NOT NULL,
  domain TEXT NOT NULL,
  root_url TEXT NOT NULL,
  depth INTEGER NOT NULL CHECK(depth >= 0),
  enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(domain, root_url)
);

CREATE INDEX IF NOT EXISTS idx_seed_urls_enabled ON seed_urls(enabled);
CREATE INDEX IF NOT EXISTS idx_seed_urls_domain ON seed_urls(domain);
