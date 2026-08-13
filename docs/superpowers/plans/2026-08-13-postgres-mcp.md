# Postgres MCP Pro (read-only SSE) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Host CrystalDBA Postgres MCP Pro behind Traefik at `https://mcp.kolberg.uz/sse` with Basic Auth and a dedicated read-only Postgres role, for Cursor / Claude Desktop.

**Architecture:** New `postgres-mcp` Docker Compose service on `backend` + `traefik-public`, SSE + `--access-mode=restricted`, Traefik Host `mcp.kolberg.uz` + Basic Auth. One login pair (`POSTGRES_MCP_USER` / `POSTGRES_MCP_PASSWORD`) for HTTP and DB; Traefik gets the bcrypt htpasswd form of that same pair. Separate from the Kolberg domain MCP on `MCP_HOST` (default `api.kolberg.uz`).

**Tech Stack:** `crystaldba/postgres-mcp:0.3.0`, Docker Compose, Traefik basicAuth, Postgres 17 (`db` service), Makefile SSH helpers.

**Spec:** `docs/superpowers/specs/2026-08-13-postgres-mcp-design.md`

## Global Constraints

- Hostname: `mcp.kolberg.uz` only — do **not** change `MCP_HOST` / domain MCP (`api.kolberg.uz` → Django).
- Access: `--access-mode=restricted` only (no unrestricted on production).
- Credentials: same `POSTGRES_MCP_USER` / `POSTGRES_MCP_PASSWORD` for Basic Auth and Postgres role; `POSTGRES_MCP_HTPASSWD` is the bcrypt encoding of that pair for Traefik (not a second login).
- Never use `POSTGRES_V2_USER` / app credentials in `DATABASE_URI`.
- No scripts that DROP tables, DELETE rows, DROP DATABASE, or CASCADE-drop roles.
- No local `manage.py test` / `pytest` / `npm test`; verify with file checks + post-deploy curl.
- Commits only on `dev/postgres-mcp` (or `fix/…`); never on `main`. All three worktree slots are currently busy — free a slot or ask the user which path to use before coding.
- `make deploy` only when the user explicitly requests it.

---

## File structure

| File | Responsibility |
|------|----------------|
| `docker-compose.yml` | Add `postgres-mcp` service (image, env, networks, Traefik labels). |
| `.env.example` | Document `POSTGRES_MCP_*` placeholders and htpasswd generation. |
| `docs/POSTGRES_MCP.md` | Operator docs: DNS, role SQL, client MCP JSON, vs domain MCP. |
| `scripts/postgres_mcp_create_readonly_role.sql` | Idempotent-ish SQL template for SELECT-only role (params via `psql` vars). |
| `Makefile` | `create-postgres-mcp-role` target (SSH → apply SQL); help text. |
| `scripts/check_postgres_mcp_compose.sh` | Local static check that compose/docs/.env.example match the contract. |

---

### Task 1: Compose service + env placeholders + static check

**Files:**
- Modify: `docker-compose.yml` (insert `postgres-mcp` service after `adminer`, before `traefik`)
- Modify: `.env.example`
- Create: `scripts/check_postgres_mcp_compose.sh`

**Interfaces:**
- Consumes: existing networks `backend`, `traefik-public`; env `POSTGRES_V2_DB`
- Produces: service name `postgres-mcp`; env keys `POSTGRES_MCP_USER`, `POSTGRES_MCP_PASSWORD`, `POSTGRES_MCP_HTPASSWD`, `POSTGRES_MCP_HOST`

- [ ] **Step 1: Add the static check script (failing until compose/env exist)**

Create `scripts/check_postgres_mcp_compose.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE="$ROOT/docker-compose.yml"
ENV_EX="$ROOT/.env.example"
fail=0
need() {
  local file="$1" pat="$2" msg="$3"
  if ! grep -qE "$pat" "$file"; then
    echo "FAIL: $msg"
    fail=1
  fi
}
need "$COMPOSE" 'container_name:[[:space:]]*postgres-mcp' "compose must define postgres-mcp container"
need "$COMPOSE" 'crystaldba/postgres-mcp:0\.3\.0' "compose must pin crystaldba/postgres-mcp:0.3.0"
need "$COMPOSE" '--access-mode=restricted' "compose must use restricted access mode"
need "$COMPOSE" '--transport=sse' "compose must use sse transport"
need "$COMPOSE" 'Host\(`\$\{POSTGRES_MCP_HOST:-mcp\.kolberg\.uz\}`\)' "compose Traefik Host must use POSTGRES_MCP_HOST default mcp.kolberg.uz"
need "$COMPOSE" 'basicauth\.users=\$\{POSTGRES_MCP_HTPASSWD\}' "compose must use POSTGRES_MCP_HTPASSWD for Basic Auth"
need "$COMPOSE" 'POSTGRES_MCP_USER' "compose DATABASE_URI must reference POSTGRES_MCP_USER"
need "$COMPOSE" 'loadbalancer\.server\.port=8000' "Traefik must target port 8000"
need "$ENV_EX" 'POSTGRES_MCP_USER=' ".env.example must document POSTGRES_MCP_USER"
need "$ENV_EX" 'POSTGRES_MCP_PASSWORD=' ".env.example must document POSTGRES_MCP_PASSWORD"
need "$ENV_EX" 'POSTGRES_MCP_HTPASSWD=' ".env.example must document POSTGRES_MCP_HTPASSWD"
need "$ENV_EX" 'POSTGRES_MCP_HOST=mcp\.kolberg\.uz' ".env.example must set POSTGRES_MCP_HOST=mcp.kolberg.uz"
if [[ "$fail" -ne 0 ]]; then
  exit 1
fi
echo "OK: postgres-mcp compose contract"
```

- [ ] **Step 2: Run check — expect FAIL**

```bash
chmod +x scripts/check_postgres_mcp_compose.sh
./scripts/check_postgres_mcp_compose.sh
```

Expected: one or more `FAIL:` lines, exit code 1.

- [ ] **Step 3: Add `postgres-mcp` service to `docker-compose.yml`**

Insert after the `adminer` service block (before `traefik:`):

```yaml
  postgres-mcp:
    image: crystaldba/postgres-mcp:0.3.0
    restart: always
    container_name: postgres-mcp
    depends_on:
      db:
        condition: service_started
    environment:
      DATABASE_URI: postgresql://${POSTGRES_MCP_USER}:${POSTGRES_MCP_PASSWORD}@db:5432/${POSTGRES_V2_DB}
    command:
      - --access-mode=restricted
      - --transport=sse
    labels:
      - traefik.enable=true
      - traefik.docker.network=n8n_traefik-public
      - traefik.http.routers.postgres-mcp.rule=Host(`${POSTGRES_MCP_HOST:-mcp.kolberg.uz}`)
      - traefik.http.routers.postgres-mcp.tls=true
      - traefik.http.routers.postgres-mcp.entrypoints=web,websecure
      - traefik.http.routers.postgres-mcp.tls.certresolver=mytlschallenge
      - traefik.http.middlewares.postgres-mcp-headers.headers.SSLRedirect=true
      - traefik.http.middlewares.postgres-mcp-headers.headers.STSSeconds=315360000
      - traefik.http.middlewares.postgres-mcp-headers.headers.browserXSSFilter=true
      - traefik.http.middlewares.postgres-mcp-headers.headers.contentTypeNosniff=true
      - traefik.http.middlewares.postgres-mcp-headers.headers.forceSTSHeader=true
      - traefik.http.middlewares.postgres-mcp-headers.headers.SSLHost=kolberg.uz
      - traefik.http.middlewares.postgres-mcp-headers.headers.STSIncludeSubdomains=true
      - traefik.http.middlewares.postgres-mcp-headers.headers.STSPreload=true
      # HTPASSWD is bcrypt of POSTGRES_MCP_USER:POSTGRES_MCP_PASSWORD (same login). Escape $ as $$ in .env for Compose.
      - traefik.http.middlewares.postgres-mcp-auth.basicauth.users=${POSTGRES_MCP_HTPASSWD}
      - traefik.http.routers.postgres-mcp.middlewares=postgres-mcp-headers@docker,postgres-mcp-auth@docker
      - traefik.http.services.postgres-mcp.loadbalancer.server.port=8000
    networks:
      - traefik-public
      - backend
```

Do **not** publish host ports. Do **not** change the `django-v2-mcp` router / `MCP_HOST`.

- [ ] **Step 4: Extend `.env.example`**

Append:

```bash
# --- Postgres MCP Pro (DBA SSE at mcp.kolberg.uz) ---
# Same login for Traefik Basic Auth AND the Postgres read-only role.
POSTGRES_MCP_HOST=mcp.kolberg.uz
POSTGRES_MCP_USER=mcp_readonly
POSTGRES_MCP_PASSWORD=change-me-strong-password
# Generate from the same user/password (bcrypt). On a machine with apache2-utils / httpd-tools:
#   htpasswd -nbB "$POSTGRES_MCP_USER" "$POSTGRES_MCP_PASSWORD"
# Put the result here; in Compose .env, escape each $ as $$.
# Example shape (not a real hash): mcp_readonly:$$2y$$05$$xxxxxxxx
POSTGRES_MCP_HTPASSWD=mcp_readonly:$$2y$$05$$replace-with-real-hash
```

- [ ] **Step 5: Run check — expect PASS**

```bash
./scripts/check_postgres_mcp_compose.sh
```

Expected: `OK: postgres-mcp compose contract`

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml .env.example scripts/check_postgres_mcp_compose.sh
git commit -m "$(cat <<'EOF'
feat: add postgres-mcp Traefik service (restricted SSE)

EOF
)"
```

---

### Task 2: Read-only role SQL + Makefile target

**Files:**
- Create: `scripts/postgres_mcp_create_readonly_role.sql`
- Modify: `Makefile` (`.PHONY`, `help`, new target `create-postgres-mcp-role`)

**Interfaces:**
- Consumes: server `.env` keys `POSTGRES_MCP_USER`, `POSTGRES_MCP_PASSWORD`, `POSTGRES_V2_DB`, `POSTGRES_V2_USER`, plus `db` superuser `POSTGRES_USER`
- Produces: `make create-postgres-mcp-role` (SSH → create/grant only)

- [ ] **Step 1: Add SQL script**

Create `scripts/postgres_mcp_create_readonly_role.sql`:

```sql
-- Params (psql): mcp_user, mcp_password, app_db, app_owner
-- Safe: CREATE/GRANT only. No DROP, DELETE, TRUNCATE, or CASCADE.

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
```

If `\gexec` + `:variables` prove awkward under `docker compose exec`, replace with an equivalent shell-escaped `psql -v` invocation in the Makefile that still only runs CREATE/GRANT/ALTER ROLE/ALTER DEFAULT PRIVILEGES (never DROP/DELETE). Keep the SQL file as the source of truth for the statements.

- [ ] **Step 2: Add Makefile target**

Near `backup-db`, add:

```makefile
# ── Postgres MCP: create/update read-only role on production DB ─────────────
create-postgres-mcp-role:
	ssh $(SERVER) 'cd $(REMOTE_DIR) && \
		set -a && . ./.env && set +a && \
		test -n "$$POSTGRES_MCP_USER" && test -n "$$POSTGRES_MCP_PASSWORD" && \
		test -n "$$POSTGRES_V2_DB" && test -n "$$POSTGRES_V2_USER" && \
		docker compose --env-file ./.env exec -T db \
		psql -U "$$POSTGRES_USER" -d postgres \
		-v mcp_user="$$POSTGRES_MCP_USER" \
		-v mcp_password="$$POSTGRES_MCP_PASSWORD" \
		-v app_db="$$POSTGRES_V2_DB" \
		-v app_owner="$$POSTGRES_V2_USER" \
		-f - < scripts/postgres_mcp_create_readonly_role.sql'
	@echo "✅  Postgres MCP read-only role ensured (CONNECT + SELECT)."
```

Also:

1. Add `create-postgres-mcp-role` to `.PHONY`.
2. Add a help line under `help:` describing the target.

Copy the SQL onto the server via the normal deploy path (repo is at `REMOTE_DIR`), or pipe file contents over SSH if `scripts/` is not yet on the server until after merge/deploy — prefer: after merge + pull on server, then run the make target. Document that order in Task 3 docs.

If `psql -f -` with local redirect does not send the file to the remote `exec`, use this equivalent instead (still CREATE/GRANT only):

```makefile
create-postgres-mcp-role:
	ssh $(SERVER) "cd $(REMOTE_DIR) && \
		set -a && . ./.env && set +a && \
		docker compose --env-file ./.env exec -T db \
		env PGPASSWORD=\"\$$POSTGRES_PASSWORD\" \
		psql -U \"\$$POSTGRES_USER\" -d postgres \
		-v mcp_user=\"\$$POSTGRES_MCP_USER\" \
		-v mcp_password=\"\$$POSTGRES_MCP_PASSWORD\" \
		-v app_db=\"\$$POSTGRES_V2_DB\" \
		-v app_owner=\"\$$POSTGRES_V2_USER\" \
		-f /dev/stdin" < scripts/postgres_mcp_create_readonly_role.sql
```

(Adjust quoting until a dry-run on a non-prod check shows the SQL reaching `psql`; do not add destructive statements while debugging.)

- [ ] **Step 3: Sanity-read the SQL for forbidden verbs**

```bash
! grep -iE '\b(DROP|DELETE|TRUNCATE|CASCADE)\b' scripts/postgres_mcp_create_readonly_role.sql
```

Expected: no matches (exit 0 from `! grep` / empty).

- [ ] **Step 4: Commit**

```bash
git add scripts/postgres_mcp_create_readonly_role.sql Makefile
git commit -m "$(cat <<'EOF'
feat: add Makefile target to create postgres-mcp read-only role

EOF
)"
```

---

### Task 3: Operator documentation

**Files:**
- Create: `docs/POSTGRES_MCP.md`
- Modify: `scripts/check_postgres_mcp_compose.sh` (also require docs file + key phrases)

**Interfaces:**
- Consumes: contract from Tasks 1–2
- Produces: operator runbook for DNS, secrets, role, clients, verification

- [ ] **Step 1: Extend check script for docs**

Append to `scripts/check_postgres_mcp_compose.sh`:

```bash
DOC="$ROOT/docs/POSTGRES_MCP.md"
need "$DOC" 'mcp\.kolberg\.uz' "docs/POSTGRES_MCP.md must document mcp.kolberg.uz"
need "$DOC" 'access-mode=restricted' "docs must mention restricted mode"
need "$DOC" 'POSTGRES_MCP_USER' "docs must document POSTGRES_MCP_USER"
need "$DOC" 'create-postgres-mcp-role' "docs must mention make create-postgres-mcp-role"
need "$DOC" 'Authorization' "docs must show Basic Auth client header"
need "$DOC" 'MCP_SERVER\.md' "docs must point to domain MCP docs as separate"
```

- [ ] **Step 2: Run check — expect FAIL on missing doc**

```bash
./scripts/check_postgres_mcp_compose.sh
```

Expected: FAIL mentioning `docs/POSTGRES_MCP.md`.

- [ ] **Step 3: Write `docs/POSTGRES_MCP.md`**

```markdown
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
```

- [ ] **Step 4: Run check — expect PASS**

```bash
./scripts/check_postgres_mcp_compose.sh
```

Expected: `OK: postgres-mcp compose contract`

- [ ] **Step 5: Commit**

```bash
git add docs/POSTGRES_MCP.md scripts/check_postgres_mcp_compose.sh
git commit -m "$(cat <<'EOF'
docs: add Postgres MCP Pro operator runbook

EOF
)"
```

---

### Task 4: PR + post-merge operator checklist (no auto-deploy)

**Files:** none required in repo beyond prior tasks; also include the design/plan docs in the PR if not already on the branch.

**Interfaces:**
- Consumes: Tasks 1–3 merged to `main`
- Produces: open PR; human runbook for DNS / `.env` / role / deploy / client

- [ ] **Step 1: Push branch and open PR**

```bash
make push
# or: git push -u origin HEAD
gh pr create --title "feat: Postgres MCP Pro on mcp.kolberg.uz (read-only)" --body "$(cat <<'EOF'
## Summary
- Add `postgres-mcp` Compose service (SSE, restricted) behind Traefik at `mcp.kolberg.uz`
- Basic Auth + DB role share `POSTGRES_MCP_USER` / `POSTGRES_MCP_PASSWORD`
- Makefile target + SQL to create SELECT-only role
- Operator docs in `docs/POSTGRES_MCP.md`

## Test plan
- [ ] `./scripts/check_postgres_mcp_compose.sh` passes
- [ ] After merge: DNS for `mcp.kolberg.uz`
- [ ] Set server `.env` + `make create-postgres-mcp-role`
- [ ] `make deploy` (explicit)
- [ ] curl without auth → 401; with auth → MCP SSE
- [ ] MCP client read works; write fails
- [ ] Confirm domain MCP on `api.kolberg.uz` unchanged

EOF
)"
```

- [ ] **Step 2: After merge (human / this session only if asked)**

1. Set DNS `mcp.kolberg.uz`.
2. Fill server `.env` (`POSTGRES_MCP_*`).
3. `make create-postgres-mcp-role`
4. Only if user asks: `make deploy`
5. Configure Cursor / Claude Desktop with Basic Auth header.
6. Run verification curls from `docs/POSTGRES_MCP.md`.

Do **not** run `make deploy` in this task unless the user explicitly requests it in the session.

---

## Spec coverage self-review

| Spec requirement | Task |
|------------------|------|
| Compose service SSE + restricted | Task 1 |
| Host `mcp.kolberg.uz` | Task 1 |
| Traefik Basic Auth from same user/password | Task 1 (`HTPASSWD` derived) |
| `DATABASE_URI` with MCP role + `POSTGRES_V2_DB` | Task 1 |
| Create DB user with SELECT + default privileges | Task 2 |
| Docs + client JSON | Task 3 |
| No change to domain MCP / `api.kolberg.uz` | Task 1 constraint + Task 3 docs |
| Post-deploy verification | Task 3 docs + Task 4 |
| No auto-deploy | Task 4 |
| hypopg / pg_stat_statements | Out of v1 (follow-up in spec) |

## Placeholder / consistency check

- Image pinned to `0.3.0` (exists on Docker Hub).
- Env names consistent: `POSTGRES_MCP_USER`, `POSTGRES_MCP_PASSWORD`, `POSTGRES_MCP_HTPASSWD`, `POSTGRES_MCP_HOST`.
- No TBD/TODO left in task steps.
