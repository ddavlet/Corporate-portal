# Postgres MCP Pro on production (read-only SSE)

- **Date:** 2026-08-13
- **Status:** approved for implementation
- **Clients:** Cursor, Claude Desktop / Claude.ai (MCP-capable)
- **Hostname:** `mcp.kolberg.uz` (not `api.kolberg.uz`)

## Context

Kolberg already has a **domain** MCP server (`backend_v2/apps/mcp_server/`, see `docs/MCP_SERVER.md`): JWT-auth’d, tenant-scoped, read-only business tools.

This design adds a complementary **DBA** MCP: [crystaldba/postgres-mcp](https://github.com/crystaldba/postgres-mcp) (Postgres MCP Pro) for schema inspection, safe SQL, health checks, and (later) index tuning. It talks to Postgres directly and is intended for operators using Cursor / Claude with a remote SSE URL.

## Goals

- Host Postgres MCP Pro on the existing production Docker/Traefik stack.
- Expose `https://mcp.kolberg.uz/sse` for Cursor and Claude Desktop.
- Production DB access in **restricted** (read-only) MCP mode.
- Single credential pair for HTTP Basic Auth and the Postgres login role.
- Create that Postgres role with **SELECT-only** grants (plus future-table defaults).

## Non-goals

- Replacing or changing the Kolberg domain MCP (`docs/MCP_SERVER.md` / any `api.kolberg.uz` MCP path).
- Unrestricted / write access to production.
- Enabling `hypopg` / `pg_stat_statements` in v1 (optional follow-up).
- New product integration points (UI / n8n / Telegram) — this is operator tooling only.
- Exposing MCP without authentication (same class of risk as public Adminer; see `docs/SECURITY_ISSUES.md`).

## Architecture

```
Cursor / Claude Desktop
        │  HTTPS + Basic Auth (POSTGRES_MCP_USER / POSTGRES_MCP_PASSWORD)
        ▼
Traefik  Host(`mcp.kolberg.uz`)  TLS (mytlschallenge)
        │  docker network (traefik-public → service)
        ▼
postgres-mcp  :8000
  --transport=sse
  --access-mode=restricted
        │  DATABASE_URI → role POSTGRES_MCP_USER
        │  backend network only to db
        ▼
Postgres (db)  app database (POSTGRES_V2_*)
  role: LOGIN + SELECT-only grants
```

Defense in depth:

1. Traefik Basic Auth blocks unauthenticated HTTP.
2. MCP `--access-mode=restricted` enforces read-only SQL transactions.
3. Postgres role has no write/DDL privileges.

## Components

### 1. Docker Compose service `postgres-mcp`

- Image: `crystaldba/postgres-mcp` (pin a stable digest/tag at implement time).
- Command: `--transport=sse --access-mode=restricted`.
- Environment:
  - `DATABASE_URI=postgresql://${POSTGRES_MCP_USER}:${POSTGRES_MCP_PASSWORD}@db:5432/${POSTGRES_V2_DB}`
    (use the same DB name `backend_v2` uses).
- Networks: `backend` + `traefik-public` (same pattern as Adminer / `backend_v2`).
- No host port publish; Traefik routes to container port `8000`.
- Traefik labels:
  - `Host(\`mcp.kolberg.uz\`)`
  - TLS + existing cert resolver
  - Security headers (same style as other public services)
  - Basic Auth middleware whose users are derived from **`POSTGRES_MCP_USER` / `POSTGRES_MCP_PASSWORD`** (not a second secret pair)
  - Load balancer port `8000`

### 2. Environment variables

Document in `.env.example` (placeholders only); real values only on the server `.env`:

| Variable | Purpose |
|----------|---------|
| `POSTGRES_MCP_USER` | Postgres role name **and** Basic Auth username |
| `POSTGRES_MCP_PASSWORD` | Postgres role password **and** Basic Auth password |
| `POSTGRES_MCP_HOST` | `mcp.kolberg.uz` (for docs / Traefik rule clarity) |

No separate `POSTGRES_MCP_BASICAUTH_*` credentials. Implementation must keep Traefik htpasswd in sync with these two vars (e.g. generate htpasswd at container start / document a one-liner used in compose).

### 3. Postgres role (create with read access)

One-time (or idempotent) server-side SQL, using the same names as env:

- `CREATE ROLE <POSTGRES_MCP_USER> LOGIN PASSWORD '…'` (or `ALTER ROLE` if exists).
- `GRANT CONNECT ON DATABASE <POSTGRES_V2_DB> TO …`
- `GRANT USAGE ON SCHEMA public` (and any other schemas the app uses).
- `GRANT SELECT ON ALL TABLES IN SCHEMA …` (and views); grant on sequences only if a tool requires it.
- `ALTER DEFAULT PRIVILEGES IN SCHEMA … GRANT SELECT ON TABLES TO …` run as the **table-owning app role** (so future migrations keep working).
- Explicitly **no** `INSERT` / `UPDATE` / `DELETE` / `TRUNCATE` / `DDL` / superuser.

Delivery:

- SQL documented in `docs/POSTGRES_MCP.md`.
- Optional safe `Makefile` helper that only creates/grants (never drops data, never `DROP ROLE` with cascade, never deletes rows).

### 4. DNS

- Point `mcp.kolberg.uz` at the same Traefik host as other `*.kolberg.uz` names.

### 5. Client configuration

Cursor / Claude Desktop example:

```json
{
  "mcpServers": {
    "postgres": {
      "type": "sse",
      "url": "https://mcp.kolberg.uz/sse",
      "headers": {
        "Authorization": "Basic <base64(POSTGRES_MCP_USER:POSTGRES_MCP_PASSWORD)>"
      }
    }
  }
}
```

### 6. Documentation

- Add `docs/POSTGRES_MCP.md`: purpose, difference from Kolberg domain MCP, env vars, role SQL, Traefik/Basic Auth, client JSON, failure modes.
- Do **not** retarget domain MCP docs to this hostname.

## Data flow / error handling

| Failure | Expected behaviour |
|---------|-------------------|
| Missing/wrong Basic Auth | Traefik `401`; MCP process not invoked |
| Valid HTTP auth, bad DB password | MCP starts but SQL tools error; fix env + role |
| Write SQL attempted | Blocked by restricted mode and/or Postgres privileges |
| Service down | Clients fail to connect to `/sse` |

## Testing / verification (no local Django test suite required for this infra piece)

After deploy:

1. `curl -I` / SSE handshake to `https://mcp.kolberg.uz/sse` without auth → `401`.
2. Same with Basic Auth → MCP SSE accepts.
3. From an MCP client: `list_schemas` / read-only `execute_sql` succeeds.
4. Attempted write SQL fails under restricted mode / role grants.
5. Confirm app credentials were **not** used in `DATABASE_URI`.

CI (`Backend Tests` / Vitest) is unchanged unless a Makefile/docs-only PR; no app code path required for v1.

## Rollout

1. Branch `dev/postgres-mcp` (worktree slot when one is free).
2. Compose + `.env.example` + docs (+ optional Makefile target).
3. PR → `main`; after merge, create DNS + role on server, set `.env`, `make deploy` (user-triggered only).
4. Configure Cursor / Claude Desktop with the SSE URL + Basic Auth header.

## Follow-ups (out of v1)

- `pg_stat_statements` + `hypopg` for index-tuning tools.
- Stronger auth (Cloudflare Access / oauth2-proxy) if Basic Auth proves insufficient for Claude.ai connectors.
- Compose profile to leave the service stopped when unused.
