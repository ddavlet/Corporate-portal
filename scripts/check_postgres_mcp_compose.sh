#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE="$ROOT/docker-compose.yml"
ENV_EX="$ROOT/.env.example"
fail=0
need() {
  local file="$1" pat="$2" msg="$3"
  if ! grep -qE -- "$pat" "$file"; then
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
DOC="$ROOT/docs/POSTGRES_MCP.md"
need "$DOC" 'mcp\.kolberg\.uz' "docs/POSTGRES_MCP.md must document mcp.kolberg.uz"
need "$DOC" 'access-mode=restricted' "docs must mention restricted mode"
need "$DOC" 'POSTGRES_MCP_USER' "docs must document POSTGRES_MCP_USER"
need "$DOC" 'create-postgres-mcp-role' "docs must mention make create-postgres-mcp-role"
need "$DOC" 'Authorization' "docs must show Basic Auth client header"
need "$DOC" 'MCP_SERVER\.md' "docs must point to domain MCP docs as separate"
if [[ "$fail" -ne 0 ]]; then
  exit 1
fi
echo "OK: postgres-mcp compose contract"
