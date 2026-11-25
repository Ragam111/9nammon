-- Migration 0014: Google sign-in links and the free-tier monthly token allowance
CREATE TABLE IF NOT EXISTS org_google_accounts (
  sub           TEXT PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE,
  email         TEXT NOT NULL,
  key_id        TEXT,
  created_at    TEXT,
  last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS org_token_usage (
  username TEXT PRIMARY KEY,
  month    TEXT    NOT NULL,
  used     INTEGER NOT NULL DEFAULT 0 CHECK (used >= 0),
  reserved INTEGER NOT NULL DEFAULT 0 CHECK (reserved >= 0)
);
