-- Migration 0012: org users, API keys, daily quota and login sessions (replaces org.json + RAM)
-- Table names avoid "sessions": 0010 already defines a VIEW with that name.
CREATE TABLE org_users (
  username     TEXT PRIMARY KEY,
  role         TEXT    NOT NULL CHECK (role IN ('USER','ADMIN','CEO')),
  password     TEXT    NOT NULL DEFAULT '',
  active       INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
  created_at   TEXT,
  display_name TEXT,
  google_email TEXT
);

CREATE TABLE org_api_keys (
  key_id      TEXT PRIMARY KEY,
  key_hash    TEXT    NOT NULL,
  prefix      TEXT,
  owner       TEXT    NOT NULL,
  tier        TEXT    NOT NULL,
  daily_limit INTEGER NOT NULL DEFAULT 0 CHECK (daily_limit >= 0),
  used_today  INTEGER NOT NULL DEFAULT 0 CHECK (used_today >= 0),
  usage_date  TEXT,
  active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
  created_at  TEXT
);
CREATE INDEX idx_org_keys_hash  ON org_api_keys(key_hash);
CREATE INDEX idx_org_keys_owner ON org_api_keys(owner);

-- per-user bucket used by org_store.check_and_consume_quota (compat wrapper)
CREATE TABLE org_user_usage (
  username   TEXT PRIMARY KEY,
  usage_date TEXT    NOT NULL,
  count      INTEGER NOT NULL DEFAULT 0 CHECK (count >= 0)
);

CREATE TABLE org_meta (
  name  TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- login sessions: only sha256(token) is stored, never the token itself
CREATE TABLE auth_sessions (
  token_hash TEXT PRIMARY KEY,
  username   TEXT NOT NULL,
  role       TEXT NOT NULL,
  tier       TEXT NOT NULL,
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL
);
CREATE INDEX idx_auth_sess_user ON auth_sessions(username);
CREATE INDEX idx_auth_sess_exp  ON auth_sessions(expires_at);
