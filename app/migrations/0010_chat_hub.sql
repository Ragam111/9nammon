-- LCA Chat Hub schema (migration 0010_chat_hub). Tables live in data/lca.db.
CREATE TABLE IF NOT EXISTS schema_version (
  version    INTEGER PRIMARY KEY,
  name       TEXT    NOT NULL,
  applied_at INTEGER NOT NULL,
  checksum   TEXT
);
CREATE TABLE IF NOT EXISTS schema_meta (
  key TEXT PRIMARY KEY, value TEXT
) WITHOUT ROWID;

CREATE TABLE personas (
  id              INTEGER PRIMARY KEY,
  uid             TEXT NOT NULL UNIQUE,
  name            TEXT NOT NULL,
  system_prompt   TEXT NOT NULL DEFAULT '',
  provider        TEXT,
  model           TEXT,
  params          TEXT,
  source_skill_id TEXT,
  archived        INTEGER NOT NULL DEFAULT 0,
  created_at      INTEGER NOT NULL,
  updated_at      INTEGER NOT NULL
);

CREATE TABLE folders (
  id           INTEGER PRIMARY KEY,
  uid          TEXT NOT NULL UNIQUE,
  parent_id    INTEGER REFERENCES folders(id) ON DELETE CASCADE,
  kind         TEXT NOT NULL DEFAULT 'folder' CHECK (kind IN ('folder','project')),
  name         TEXT NOT NULL,
  instructions TEXT,
  persona_id   INTEGER REFERENCES personas(id) ON DELETE SET NULL,
  sort         INTEGER NOT NULL DEFAULT 0,
  created_at   INTEGER NOT NULL,
  updated_at   INTEGER NOT NULL
);

CREATE TABLE conversations (
  id             INTEGER PRIMARY KEY,
  uid            TEXT NOT NULL UNIQUE,
  folder_id      INTEGER REFERENCES folders(id) ON DELETE SET NULL,
  persona_id     INTEGER REFERENCES personas(id) ON DELETE SET NULL,
  owner          TEXT,
  title          TEXT NOT NULL DEFAULT '',
  system_prompt  TEXT,
  active_leaf_id INTEGER,
  pinned         INTEGER NOT NULL DEFAULT 0,
  archived       INTEGER NOT NULL DEFAULT 0,
  created_at     INTEGER NOT NULL,
  updated_at     INTEGER NOT NULL
);

CREATE TABLE messages (
  id              INTEGER PRIMARY KEY,
  uid             TEXT NOT NULL UNIQUE,
  conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  parent_id       INTEGER REFERENCES messages(id),
  role            TEXT NOT NULL CHECK (role IN ('system','user','assistant','tool')),
  origin          TEXT CHECK (origin IN ('edit','regen','branch','compare','import')),
  source_id       INTEGER,
  last_child_id   INTEGER,
  compare_id      INTEGER,
  content         TEXT NOT NULL DEFAULT '',
  provider        TEXT,
  model           TEXT,
  connection_id   TEXT,
  status          TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok','streaming','error','stopped')),
  tokens_in       INTEGER,
  tokens_out      INTEGER,
  tokens_est      INTEGER NOT NULL DEFAULT 0,
  latency_ms      INTEGER,
  extra           TEXT,
  created_at      INTEGER NOT NULL
);

CREATE TABLE blobs (
  sha256     TEXT PRIMARY KEY,
  size       INTEGER NOT NULL,
  mime       TEXT NOT NULL,
  width      INTEGER, height INTEGER,
  created_at INTEGER NOT NULL
) WITHOUT ROWID;

CREATE TABLE attachments (
  id         INTEGER PRIMARY KEY,
  uid        TEXT NOT NULL UNIQUE,
  message_id INTEGER REFERENCES messages(id) ON DELETE CASCADE,
  folder_id  INTEGER REFERENCES folders(id) ON DELETE CASCADE,
  sha256     TEXT NOT NULL,
  filename   TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  CHECK ((message_id IS NULL) <> (folder_id IS NULL))
);

CREATE TABLE tags (
  id    INTEGER PRIMARY KEY,
  name  TEXT NOT NULL UNIQUE COLLATE NOCASE,
  color TEXT
);
CREATE TABLE conversation_tags (
  conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  tag_id          INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  PRIMARY KEY (conversation_id, tag_id)
) WITHOUT ROWID;

-- Thai/English search: contentless FTS5, body = Python pre-segmented tokens.
CREATE VIRTUAL TABLE msg_fts USING fts5(body, content='', tokenize='ascii');

-- The plan's sessions table is renamed to conversations. 0001_init must not create sessions.
CREATE VIEW IF NOT EXISTS sessions AS SELECT * FROM conversations;

CREATE INDEX idx_msg_conv    ON messages(conversation_id);
CREATE INDEX idx_msg_parent  ON messages(parent_id);
CREATE INDEX idx_conv_folder ON conversations(folder_id, updated_at);
CREATE INDEX idx_att_msg     ON attachments(message_id) WHERE message_id IS NOT NULL;
CREATE INDEX idx_att_folder  ON attachments(folder_id)  WHERE folder_id  IS NOT NULL;
CREATE INDEX idx_ctag_tag    ON conversation_tags(tag_id);
