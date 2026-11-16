-- Migration 0011: server_events — audit log สำหรับ event สำคัญของ server
CREATE TABLE server_events (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  kind    TEXT    NOT NULL,
  level   TEXT    NOT NULL DEFAULT 'info'
            CHECK (level IN ('debug','info','warn','error')),
  source  TEXT,
  message TEXT    NOT NULL DEFAULT '',
  extra   TEXT,
  ts      INTEGER NOT NULL
            DEFAULT (CAST(strftime('%s','now') AS INTEGER))
);
CREATE INDEX idx_sevt_kind  ON server_events(kind, ts);
CREATE INDEX idx_sevt_level ON server_events(level, ts);
