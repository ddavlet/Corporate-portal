import os

from apps.tenants.models import TenantUserRole

AGENT_MODEL = "claude-sonnet-5-5"
AGENT_EFFORT = "medium"
AGENT_MAX_TOKENS = 16000
AGENT_MAX_STEPS = 12
# Классификатор «кому адресовано» для групп. Нужна точность, поэтому не Haiku, а
# Opus 5.5 с adaptive thinking (отключить нельзя), запас max_tokens под рассуждение.
ADDRESSEE_MODEL = "claude-opus-5-5"
ADDRESSEE_EFFORT = "medium"
ADDRESSEE_MAX_TOKENS = 8000
ADDRESSEE_CONTEXT_NODES = 6
ADDRESSEE_TEXT_LIMIT = 1500
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Разрешает thinking.block_binding: thinking-блоки, не прошедшие проверку префикса
# (изменился system/tools/история), отбрасываются вместо ошибки 400.
THINKING_BINDING_BETA = "thinking-binding-controls-2026-08-01"

ALLOWED_ROLES = frozenset(
    {
        TenantUserRole.ROLE_ADMIN,
        TenantUserRole.ROLE_DIRECTOR,
        TenantUserRole.ROLE_INVESTOR,
    }
)

# Decimal strings, USD per million tokens.
MODEL_PRICES_USD_PER_MTOK = {
    "claude-sonnet-5-5": {"input": "2.00", "output": "10.00", "cache_read": "0.20", "cache_write": "2.50"},
    # Серверный fallback (fallbacks="default") отправляет отказ Sonnet 5.5 на Sonnet 5 — те же цены.
    "claude-sonnet-5": {"input": "2.00", "output": "10.00", "cache_read": "0.20", "cache_write": "2.50"},
    "claude-opus-5-5": {"input": "4.00", "output": "20.00", "cache_read": "0.20", "cache_write": "5.00"},
}

CHAIN_TTL_DAYS = 7
CONFIRMATION_TTL_HOURS = 24
MCP_TOKEN_MINUTES = 15
MCP_INTERNAL_URL = os.getenv("AI_ASSISTANT_MCP_URL", "http://backend_v2:8001/mcp/")
EXECUTOR_MAX_WORKERS = 4
CALLBACK_PREFIX = "aiq:"
TELEGRAM_TEXT_LIMIT = 4096
