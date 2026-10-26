"""
Copy a tenant's configuration (not its data) into another tenant — used to
open a new branch from an existing one.

Tenant-level parts live here: tenant flags/ID formats, enabled modules and
(optionally) members with their roles. Each module copies its own settings in
`apps/modules/<module>/tenant_config_clone.py` exposing
`clone(ctx: CloneContext) -> None`; a module that is missing or fails to import
is skipped with a warning, so an unplugged module never blocks the rest.

Rules shared by every step:
  * only what the target lacks is added — existing target settings are never
    overwritten or deleted, so a re-run is a no-op. The one exception: modules
    enabled in the source are switched on in the target;
  * users are copied only if they are members of the target (approval steps
    left without approvers are created disabled);
  * Telegram group chats are copied only when they are group-wide (registered
    in some other tenant too); a branch-only chat (e.g. its cashier chat) is
    not, and settings pointing at it are left empty;
  * bot-specific web-app links are rewritten to the target's bot, or left empty
    while the target has no bot yet (a re-run fills them in).

Dry-run runs the same code inside a rolled-back transaction.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from django.apps import apps as django_apps
from django.db import transaction
from django.utils.module_loading import import_string

from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

logger = logging.getLogger(__name__)

MODULE_CLONE_STEPS = (
    "apps.modules.requests.tenant_config_clone.clone",
    "apps.modules.investments.tenant_config_clone.clone",
    "apps.modules.reports.tenant_config_clone.clone",
    "apps.modules.cash_withdrawals.tenant_config_clone.clone",
    "apps.modules.wallets.tenant_config_clone.clone",
)

# Copied only while the target still has the model default (fresh tenant).
_TENANT_FIELDS = (
    "cash_expense_external_id_prefix",
    "cash_expense_external_id_digit_width",
    "payroll_doc_id_prefix",
    "payroll_doc_id_digit_width",
    "create_payment_request_on_payroll_accrual",
    "payroll_payout_mode",
)

_BOT_LINK_RE = re.compile(r"(https?://t\.me/)([A-Za-z0-9_]+)(/)")


@dataclass
class CloneContext:
    source: Tenant
    target: Tenant
    changes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    _chat_cache: dict = field(default_factory=dict)

    def change(self, line: str) -> None:
        self.changes.append(line)

    def warn(self, line: str) -> None:
        self.warnings.append(line)

    def target_member_ids(self) -> set[int]:
        return set(
            TenantMembership.objects.filter(tenant=self.target, is_active=True).values_list("user_id", flat=True)
        )

    def bot_link(self, url: str) -> str:
        """Point a t.me/<bot>/... web-app link at the target's bot ("" while it has none)."""
        if not url or not _BOT_LINK_RE.search(url):
            return url
        bot = (self.target.telegram_bot_username or "").lstrip("@").strip()
        if not bot:
            return ""
        return _BOT_LINK_RE.sub(lambda m: f"{m.group(1)}{bot}{m.group(3)}", url, count=1)

    def chat(self, source_chat):
        """Target TenantTelegramChat for a source chat, or None for a branch-only chat."""
        if source_chat is None:
            return None
        if source_chat.pk in self._chat_cache:
            return self._chat_cache[source_chat.pk]
        chat_model = type(source_chat)
        target_chat = chat_model.objects.filter(tenant=self.target, chat_id=source_chat.chat_id).first()
        if target_chat is None:
            shared = (
                chat_model.objects.filter(chat_id=source_chat.chat_id)
                .exclude(tenant__in=[self.source, self.target])
                .exists()
            )
            if shared:
                target_chat = chat_model.objects.create(
                    tenant=self.target, name=source_chat.name, chat_id=source_chat.chat_id, is_active=source_chat.is_active,
                )
                self.change(f"Telegram-чат «{source_chat.name}» добавлен — добавьте в него бота нового тенанта.")
            else:
                self.warn(
                    f"Telegram-чат «{source_chat.name}» есть только у {self.source.subdomain} — не скопирован, "
                    f"настройки, где он был указан, оставлены без чата."
                )
        self._chat_cache[source_chat.pk] = target_chat
        return target_chat


@dataclass
class CloneReport:
    target: Tenant
    created: bool
    changes: list[str]
    warnings: list[str]


def _resolve_target(*, subdomain: str, name: str | None) -> tuple[Tenant, bool]:
    target = Tenant.objects.filter(subdomain=subdomain).first()
    if target is not None:
        return target, False
    if not name:
        raise ValueError(f"Tenant {subdomain!r} not found — pass a name to create it.")
    return Tenant.objects.create(subdomain=subdomain, name=name, is_active=True), True


def _clone_tenant_fields(ctx: CloneContext) -> None:
    changed: list[str] = []
    for name in _TENANT_FIELDS:
        default = Tenant._meta.get_field(name).get_default()
        source_value = getattr(ctx.source, name)
        if getattr(ctx.target, name) == default and source_value != default:
            setattr(ctx.target, name, source_value)
            changed.append(name)
            ctx.change(f"Тенант: {name} = {source_value!r}.")
    if changed:
        ctx.target.save(update_fields=changed)
    if ctx.source.telegram_otp_enabled and not ctx.target.telegram_otp_enabled:
        ctx.warn("Вход по Telegram OTP не включён: сначала задайте бота тенанта, затем включите вручную.")
    if not ctx.target.telegram_bot_username:
        ctx.warn("У тенанта нет Telegram-бота — ссылки web-app в шагах оплаты оставлены пустыми; повторите запуск после настройки бота.")


def _clone_modules(ctx: CloneContext) -> None:
    from apps.modules.registry import list_modules

    known = {m["module_key"] for m in list_modules()}
    target_rows = {row.module_key: row for row in TenantModuleConfig.objects.filter(tenant=ctx.target)}
    for row in TenantModuleConfig.objects.filter(tenant=ctx.source, is_enabled=True, module_key__in=known):
        target_row = target_rows.get(row.module_key)
        if target_row is None:
            TenantModuleConfig.objects.create(tenant=ctx.target, module_key=row.module_key, is_enabled=True)
        elif not target_row.is_enabled:
            target_row.is_enabled = True
            target_row.save(update_fields=["is_enabled"])
        else:
            continue
        ctx.change(f"Модуль {row.module_key} включён.")


def _clone_members(ctx: CloneContext) -> None:
    memberships = {m.user_id: m for m in TenantMembership.objects.filter(tenant=ctx.target)}
    target_roles = set(TenantUserRole.objects.filter(tenant=ctx.target).values_list("user_id", "role"))
    for membership in TenantMembership.objects.filter(tenant=ctx.source, is_active=True).select_related("user"):
        label = membership.user.full_name or membership.user.username
        existing = memberships.get(membership.user_id)
        if existing is None:
            TenantMembership.objects.create(tenant=ctx.target, user_id=membership.user_id, is_active=True)
            ctx.change(f"Участник {label} добавлен.")
        elif not existing.is_active:
            # Deactivated in the target on purpose — do not bring the user back.
            ctx.warn(f"Участник {label} отключён в целевом тенанте — оставлен отключённым.")
            continue
        roles = TenantUserRole.objects.filter(tenant=ctx.source, user_id=membership.user_id).values_list("role", flat=True)
        for role in roles:
            if (membership.user_id, role) not in target_roles:
                TenantUserRole.objects.create(tenant=ctx.target, user_id=membership.user_id, role=role)
                ctx.change(f"Роль {role} для {label}.")


def _warn_integrations(ctx: CloneContext) -> None:
    try:
        integration_model = django_apps.get_model("tenants", "TenantIntegrationConfig")
    except LookupError:
        return
    if integration_model.objects.filter(tenant=ctx.source).exists() and not integration_model.objects.filter(
        tenant=ctx.target
    ).exists():
        ctx.warn("Интеграции (n8n-токен, Telegram OIDC, ИИ-чат) не копируются — настройте их для тенанта отдельно.")


def clone_tenant_config(
    *, source: Tenant, target_subdomain: str, target_name: str | None, with_members: bool, apply_changes: bool,
) -> CloneReport:
    with transaction.atomic():
        target, created = _resolve_target(subdomain=target_subdomain, name=target_name)
        if target.pk == source.pk:
            raise ValueError("Source and target are the same tenant.")
        ctx = CloneContext(source=source, target=target)
        if created:
            ctx.change(f"Тенант {target.subdomain} («{target.name}») создан.")

        _clone_tenant_fields(ctx)
        _clone_modules(ctx)
        if with_members:
            _clone_members(ctx)
        elif not ctx.target_member_ids():
            ctx.warn("Участники не копировались (нет --with-members): согласующие и заявители не будут назначены.")

        for path in MODULE_CLONE_STEPS:
            try:
                step = import_string(path)
            except ImportError:
                logger.warning("tenant config clone: step %s is unavailable, skipped", path)
                ctx.warn(f"Шаг {path} недоступен — пропущен.")
                continue
            step(ctx)

        _warn_integrations(ctx)
        ctx.warn("Остатки касс, банковские счета, карты, поставщики и сотрудники не копируются — это данные филиала.")

        if not apply_changes:
            transaction.set_rollback(True)
    return CloneReport(target=target, created=created, changes=ctx.changes, warnings=ctx.warnings)
