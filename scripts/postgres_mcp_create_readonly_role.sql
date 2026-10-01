-- Params (psql): mcp_user, mcp_password, app_db, app_owner
-- Safe: CREATE/GRANT/REVOKE/ALTER ROLE/ALTER DEFAULT PRIVILEGES only (plus a session-local TEMP table).

\set ON_ERROR_STOP on

SELECT format('CREATE ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT',
              :'mcp_user', :'mcp_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'mcp_user')\gexec

SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT',
              :'mcp_user', :'mcp_password')
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'mcp_user')\gexec

SELECT format('GRANT CONNECT ON DATABASE %I TO %I', :'app_db', :'mcp_user')\gexec

\connect :app_db

-- One transaction: re-running the script never leaves secrets readable between GRANT and REVOKE.
BEGIN;

SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'mcp_user')\gexec
SELECT format('GRANT SELECT ON ALL TABLES IN SCHEMA public TO %I', :'mcp_user')\gexec
SELECT format('GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO %I', :'mcp_user')\gexec

-- Future tables created by the app role must grant SELECT to mcp user.
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT ON TABLES TO %I',
              :'app_owner', :'mcp_user')\gexec
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT ON SEQUENCES TO %I',
              :'app_owner', :'mcp_user')\gexec

-- Secrets: auth plumbing tables, fully closed (nothing useful for analytics there).
-- Guarded by apps/common/test_postgres_mcp_role.py — keep the VALUES format.
SELECT format('REVOKE SELECT ON TABLE %I FROM %I', t.tbl, :'mcp_user')
FROM (VALUES
    ('django_session'),
    ('accounts_otpchallenge'),
    ('mcp_oauth_authorization_code')
) AS t(tbl)
WHERE to_regclass('public.' || quote_ident(t.tbl)) IS NOT NULL\gexec

-- Secrets: individual columns. The table grant is replaced with a column-level grant on every
-- other column, so `SELECT *` on these tables fails — list the columns explicitly.
-- A column added later to one of these tables stays hidden until the script is re-run.
CREATE TEMP TABLE mcp_hidden_columns (tbl text, col text) ON COMMIT DROP;
INSERT INTO mcp_hidden_columns (tbl, col) VALUES
    ('accounts_user', 'password'),
    ('tenants_tenant', 'telegram_bot_token_enc'),
    ('tenant_integration_configs', 'n8n_integration_token_enc'),
    ('tenant_integration_configs', 'requests_file_gateway_token_enc'),
    ('tenant_integration_configs', 'telegram_oidc_client_secret_enc'),
    ('tenant_integration_configs', 'request_ai_chat_webhook_url'),
    ('mcp_service_credential', 'key_hash'),
    ('mcp_oauth_client', 'client_secret'),
    ('invest_payout_schedule_share_links', 'token');

-- Table-level REVOKE also drops any column-level grants left from a previous run.
SELECT format('REVOKE SELECT ON TABLE %I FROM %I', t.tbl, :'mcp_user')
FROM (SELECT DISTINCT tbl FROM mcp_hidden_columns) AS t
WHERE to_regclass('public.' || quote_ident(t.tbl)) IS NOT NULL\gexec

SELECT format('GRANT SELECT (%s) ON TABLE %I TO %I',
              string_agg(quote_ident(c.column_name), ', ' ORDER BY c.ordinal_position),
              c.table_name, :'mcp_user')
FROM information_schema.columns c
WHERE c.table_schema = 'public'
  AND c.table_name IN (SELECT tbl FROM mcp_hidden_columns)
  AND NOT EXISTS (
      SELECT 1 FROM mcp_hidden_columns h
      WHERE h.tbl = c.table_name AND h.col = c.column_name
  )
GROUP BY c.table_name\gexec

COMMIT;
