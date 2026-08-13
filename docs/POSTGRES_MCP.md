# Postgres MCP Pro (production)

DBA-oriented MCP ([crystaldba/postgres-mcp](https://github.com/crystaldba/postgres-mcp)) for Cursor / Claude Desktop.

- **URL:** `https://mcp.kolberg.uz/sse`
- **Mode:** `--access-mode=restricted` (read-only SQL)
- **Auth:** HTTP Basic Auth — same user/password as the Postgres role (`POSTGRES_MCP_USER` / `POSTGRES_MCP_PASSWORD`)

This is **not** the Kolberg domain MCP (tenant/JWT business tools). See [`MCP_SERVER.md`](MCP_SERVER.md). Domain MCP stays on `MCP_HOST` (default `api.kolberg.uz`).

## One-time setup (after merge)

1. DNS: `mcp.kolberg.uz` → same Traefik host as other `*.kolberg.uz`.
2. On the server `.env`, set:
   - `POSTGRES_MCP_HOST=mcp.kolberg.uz`
   - `POSTGRES_MCP_USER=…`
   - `POSTGRES_MCP_PASSWORD=…`
   - `POSTGRES_MCP_HTPASSWD=…` — output of `htpasswd -nbB "$POSTGRES_MCP_USER" "$POSTGRES_MCP_PASSWORD"` with each `$` escaped as `$$` for Compose.
3. Pull `main`, then: `make create-postgres-mcp-role`
4. User-triggered: `make deploy` (starts `postgres-mcp` via Compose).

## Client config (Cursor / Claude Desktop)

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

## Verification

```bash
# No auth → 401
curl -sI https://mcp.kolberg.uz/sse | head -n1

# With auth (example) → not 401
curl -sI -u "$POSTGRES_MCP_USER:$POSTGRES_MCP_PASSWORD" https://mcp.kolberg.uz/sse | head -n1
```

From an MCP client: `list_schemas` / read-only `execute_sql` should work; writes should fail.

## Failure modes

| Symptom | Likely cause |
|---------|----------------|
| 401 | Wrong Basic Auth / bad `POSTGRES_MCP_HTPASSWD` escaping |
| SQL auth errors | Role not created or password mismatch — re-run `make create-postgres-mcp-role` |
| Writes succeed | Misconfiguration — must be restricted + SELECT-only role; stop and fix before continuing |
