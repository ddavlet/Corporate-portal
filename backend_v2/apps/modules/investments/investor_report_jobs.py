"""Weekly investor report: scheduled (hourly backend_cron), manual and test sends.

Each tenant's report goes to its own Telegram group via the tenant's bot (TelegramDispatcher),
so the message lands in TelegramMessage/TelegramMessageHistory; InvestReportDispatch is the
journal and the dedup key for scheduled sends.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.modules.investments.investor_report import build_investor_report
from apps.modules.investments.investor_report_formatter import format_investor_report
from apps.modules.investments.models import InvestReportConfig, InvestReportDispatch
from apps.modules.requests.integration_settings import get_requests_messaging_gateway_settings
from apps.modules.telegram_approvals.services import TelegramDispatcher
from apps.tenants.models import Tenant

logger = logging.getLogger(__name__)

MODULE_KEY = "investments"
NOT_DELIVERED_ERROR = "Сообщение не доставлено: gateway не принял отправку (бот не в группе или gateway недоступен)."
NO_CHAT_ERROR = "Telegram-группа не выбрана или отключена."


def render_report(*, tenant, config, today: dt.date) -> str:
    report = build_investor_report(tenant=tenant, today=today, config=config)
    return format_investor_report(report, tenant_name=tenant.name)


def group_recipient_id(config) -> str | None:
    chat = getattr(config, "telegram_chat", None) if config is not None else None
    if chat is None or not chat.is_active:
        return None
    return str(chat.chat_id)


def send_report(
    *, tenant, config, today: dt.date, kind: str, recipient_id: str | None, user=None
) -> InvestReportDispatch:
    """Build, send and journal one report. Never raises on build/send errors: they become ``failed``."""
    text = ""
    message = None
    error = ""
    if not recipient_id:
        error = NO_CHAT_ERROR
        logger.error("investor_report: no recipient tenant_id=%s kind=%s", tenant.pk, kind)
    else:
        try:
            text = render_report(tenant=tenant, config=config, today=today)
            action = get_requests_messaging_gateway_settings(tenant=tenant).send_action
            message = TelegramDispatcher(tenant).send(action=action, recipient_id=recipient_id, text=text)
            if message is None:
                error = NOT_DELIVERED_ERROR
                logger.error(
                    "investor_report: not delivered tenant_id=%s recipient=%s kind=%s", tenant.pk, recipient_id, kind
                )
        except Exception as exc:
            logger.exception("investor_report: send failed tenant_id=%s recipient=%s kind=%s", tenant.pk, recipient_id, kind)
            error = f"{type(exc).__name__}: {exc}"
    return InvestReportDispatch.objects.create(
        tenant=tenant,
        report_date=today,
        kind=kind,
        status=InvestReportDispatch.Status.SENT if message is not None else InvestReportDispatch.Status.FAILED,
        chat_id=recipient_id or "",
        text=text,
        telegram_message=message,
        error=error,
        created_by=user,
    )


def _enabled_tenant_ids() -> set[int]:
    from apps.tenants.models import TenantModuleConfig

    return set(
        TenantModuleConfig.objects.filter(module_key=MODULE_KEY, is_enabled=True).values_list("tenant_id", flat=True)
    )


def due_report_configs(*, local_now: dt.datetime, tenant_subdomain: str | None = None) -> list[InvestReportConfig]:
    configs = InvestReportConfig.objects.filter(
        is_active=True,
        tenant__is_active=True,
        tenant_id__in=_enabled_tenant_ids(),
        weekday=local_now.weekday(),
        send_hour=local_now.hour,
    ).select_related("tenant", "telegram_chat")
    if tenant_subdomain:
        configs = configs.filter(tenant__subdomain=tenant_subdomain)
    return list(configs.order_by("tenant_id"))


def _already_sent(*, tenant_id: int, today: dt.date) -> bool:
    return InvestReportDispatch.objects.filter(
        tenant_id=tenant_id,
        report_date=today,
        kind=InvestReportDispatch.Kind.SCHEDULED,
        status=InvestReportDispatch.Status.SENT,
    ).exists()


def _send_scheduled(*, config_id: int, today: dt.date) -> InvestReportDispatch | None:
    # Row lock serialises overlapping cron runs: the second one sees the «sent» row and skips.
    with transaction.atomic():
        config = (
            InvestReportConfig.objects.select_for_update(of=("self",))
            .select_related("tenant", "telegram_chat")
            .get(pk=config_id)
        )
        if _already_sent(tenant_id=config.tenant_id, today=today):
            return None
        return send_report(
            tenant=config.tenant,
            config=config,
            today=today,
            kind=InvestReportDispatch.Kind.SCHEDULED,
            recipient_id=group_recipient_id(config),
        )


def process_due_reports(*, now_dt: dt.datetime | None = None, tenant_subdomain: str | None = None) -> int:
    """Send scheduled reports due this hour (Asia/Tashkent). Returns the number sent."""
    local_now = timezone.localtime(now_dt or timezone.now())
    today = local_now.date()
    sent = 0
    for config in due_report_configs(local_now=local_now, tenant_subdomain=tenant_subdomain):
        try:
            dispatch = _send_scheduled(config_id=config.pk, today=today)
        except IntegrityError:
            logger.warning("investor_report: duplicate scheduled send skipped tenant_id=%s date=%s", config.tenant_id, today)
            continue
        except Exception:
            logger.exception("investor_report: tenant crashed tenant_id=%s", config.tenant_id)
            continue
        if dispatch is not None and dispatch.status == InvestReportDispatch.Status.SENT:
            sent += 1
    return sent


@dataclass(frozen=True)
class DryRunReport:
    tenant: Tenant
    chat_id: str | None
    is_due: bool
    text: str
    error: str = ""


def dry_run_reports(*, now_dt: dt.datetime | None = None, tenant_subdomain: str | None = None) -> list[DryRunReport]:
    """
    Texts for every active tenant with the module on (saved config or defaults), regardless of
    is_active/weekday/hour — to compare with n8n before switching. Sends and writes nothing.
    """
    local_now = timezone.localtime(now_dt or timezone.now())
    today = local_now.date()
    tenants = Tenant.objects.filter(is_active=True, pk__in=_enabled_tenant_ids()).order_by("id")
    if tenant_subdomain:
        tenants = tenants.filter(subdomain=tenant_subdomain)
    configs = {
        c.tenant_id: c
        for c in InvestReportConfig.objects.filter(tenant__in=tenants).select_related("telegram_chat")
    }
    due_ids = {c.tenant_id for c in due_report_configs(local_now=local_now, tenant_subdomain=tenant_subdomain)}
    out = []
    for tenant in tenants:
        config = configs.get(tenant.pk)
        try:
            text, error = render_report(tenant=tenant, config=config, today=today), ""
        except Exception as exc:
            logger.exception("investor_report: dry-run failed tenant_id=%s", tenant.pk)
            text, error = "", f"{type(exc).__name__}: {exc}"
        out.append(
            DryRunReport(
                tenant=tenant,
                chat_id=group_recipient_id(config),
                is_due=tenant.pk in due_ids and not _already_sent(tenant_id=tenant.pk, today=today),
                text=text,
                error=error,
            )
        )
    return out
