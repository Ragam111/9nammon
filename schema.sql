-- LCA multi-tenant schema (PostgreSQL 15+)
-- Model: shared database, shared schema, tenant_id on every row,
-- enforced by Row-Level Security (RLS) as a second line of defense.
-- Run this as an admin/owner role, NOT as the app role.

CREATE TABLE tenants (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name                text NOT NULL,
    plan                text NOT NULL DEFAULT 'standard',
    monthly_token_quota bigint NOT NULL DEFAULT 1000000,
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email      text NOT NULL,
    role       text NOT NULL DEFAULT 'member',   -- admin | member
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, email)
);

-- Auth lookup table: no RLS, because we must find the tenant BEFORE we know it.
-- Store only a SHA-256 hash of the key, never the key itself.
CREATE TABLE api_keys (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id    uuid REFERENCES users(id) ON DELETE CASCADE,
    key_hash   text NOT NULL UNIQUE,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE chat_sessions (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id    uuid REFERENCES users(id) ON DELETE SET NULL,
    title      text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE usage_events (
    id                bigserial PRIMARY KEY,
    tenant_id         uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id           uuid,
    model             text NOT NULL,
    prompt_tokens     int  NOT NULL DEFAULT 0,
    completion_tokens int  NOT NULL DEFAULT 0,
    created_at        timestamptz NOT NULL DEFAULT now()
);

-- Fast quota check: one row per tenant per month
CREATE TABLE usage_monthly (
    tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    month       date NOT NULL,                   -- first day of month
    tokens_used bigint NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, month)
);

CREATE INDEX idx_users_tenant          ON users (tenant_id);
CREATE INDEX idx_sessions_tenant       ON chat_sessions (tenant_id, created_at DESC);
CREATE INDEX idx_usage_events_tenant   ON usage_events (tenant_id, created_at DESC);

-- ---------------------------------------------------------------
-- Row-Level Security
-- The app sets:  SELECT set_config('app.tenant_id', '<uuid>', true);
-- If it is unset, current_setting(..., true) is NULL -> no rows visible.
-- FORCE makes RLS apply even to the table owner.
-- ---------------------------------------------------------------
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['users', 'chat_sessions', 'usage_events', 'usage_monthly']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format($p$
            CREATE POLICY tenant_isolation ON %I
            USING      (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        $p$, t);
    END LOOP;
END $$;

ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenants FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_self ON tenants
    USING (id = nullif(current_setting('app.tenant_id', true), '')::uuid);

-- ---------------------------------------------------------------
-- App role: least privilege, not a superuser, not the table owner.
-- (Superusers and BYPASSRLS roles skip RLS entirely.)
-- ---------------------------------------------------------------
CREATE ROLE lca_app LOGIN PASSWORD 'change-me';
GRANT SELECT ON tenants, api_keys TO lca_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON users, chat_sessions, usage_events, usage_monthly TO lca_app;
GRANT USAGE ON SEQUENCE usage_events_id_seq TO lca_app;

-- ---------------------------------------------------------------
-- Quick isolation test (run as lca_app after inserting 2 tenants):
--   BEGIN;
--   SELECT set_config('app.tenant_id', '<tenant A uuid>', true);
--   SELECT count(*) FROM chat_sessions;   -- only tenant A rows
--   INSERT INTO chat_sessions (tenant_id) VALUES ('<tenant B uuid>');  -- must FAIL
--   ROLLBACK;
-- ---------------------------------------------------------------
