-- Migration 0013: display name and issuer for API keys (LCA Console /console/keys)
ALTER TABLE org_api_keys ADD COLUMN name TEXT;
ALTER TABLE org_api_keys ADD COLUMN created_by TEXT;
