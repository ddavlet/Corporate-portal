-- Params (psql): mcp_user, mcp_password, app_db, app_owner
-- Safe: CREATE/GRANT/ALTER ROLE/ALTER DEFAULT PRIVILEGES only.

SELECT format('CREATE ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT',
              :'mcp_user', :'mcp_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'mcp_user')\gexec

SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT',
              :'mcp_user', :'mcp_password')
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'mcp_user')\gexec

SELECT format('GRANT CONNECT ON DATABASE %I TO %I', :'app_db', :'mcp_user')\gexec

\connect :app_db

SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'mcp_user')\gexec
SELECT format('GRANT SELECT ON ALL TABLES IN SCHEMA public TO %I', :'mcp_user')\gexec
SELECT format('GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO %I', :'mcp_user')\gexec

-- Future tables created by the app role must grant SELECT to mcp user.
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT ON TABLES TO %I',
              :'app_owner', :'mcp_user')\gexec
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT ON SEQUENCES TO %I',
              :'app_owner', :'mcp_user')\gexec
