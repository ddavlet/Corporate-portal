"""One Kapitalbank import run: daytime (today), nightly (account list + last 5 days + today), manual.

Per enabled tenant and per LINKED account: fetch the statement of every day, create the
missing rows (ingest is create-only and atomic per call), then alert. Alerts are sent
outside any transaction and never fail the run. Today's balance is reconciled only after
a self-heal re-fetch of the last days, so a back-dated document is not a false alarm.

Every failure is isolated to its account (or tenant) and recorded; the bank login and
password never reach logs, SyncEvent rows or alert texts. Runs never overlap: a global
Postgres advisory lock is held for the whole run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Callable, Literal

from django.db import connection as db_connection
from django.utils import timezone

from apps.modules.wallets.services import wallet_balance_payload

from . import alerts as kb_alerts
from .accounts import refresh_account_list
from .client import KapitalbankClient, KapitalbankError, Statement, StatementDoc
from .ingest import IngestError, existing_external_ids, ingest_statement
from .mapping import is_incoming
from .models import AccountSyncState, BankAccountLink, KapitalbankConnection, SyncEvent

logger = logging.getLogger(__name__)

NIGHTLY_DAYS_BACK = 5
DOWN_AFTER = timedelta(hours=1)
LOCK_ID = 7_301_026

Mode = Literal["daytime", "nightly", "manual"]

_CENTS = Decimal("0.01")
_MAX_MESSAGE = 2000
_UNTRACKED = (BankAccountLink.PENDING, BankAccountLink.IGNORED)


@dataclass
class RunReport:
    skipped_locked: bool = False
    accounts_ok: int = 0
    accounts_failed: int = 0
    created: int = 0
    alerts: int = 0
    # One entry per loaded (account, day): what was created, or would be in dry_run.
    details: list[dict] = field(default_factory=list)


def default_client_factory(conn: KapitalbankConnection) -> KapitalbankClient:
    return KapitalbankClient(conn.login, conn.get_password())


def days_for(mode: Mode, today: date, days: list[date] | None = None) -> list[date]:
    if mode == "daytime":
        return [today]
    if mode == "nightly":
        return [today - timedelta(days=n) for n in range(NIGHTLY_DAYS_BACK, -1, -1)]
    if mode == "manual":
        if not days:
            raise ValueError("manual mode requires days")
        return list(days)
    raise ValueError(f"Unknown mode: {mode!r}")


@dataclass
class _Run:
    mode: Mode
    now: datetime
    today: date
    days: list[date]
    dry_run: bool
    report: RunReport


class _Secrets:
    """Redacts the tenant's bank login and password from any text we store or send."""

    def __init__(self, *values: str):
        self._values = [v for v in values if v]

    def redact(self, text: str) -> str:
        for value in self._values:
            text = text.replace(value, "***")
        return text


def run(
    *,
    mode: Mode,
    now: datetime,
    tenant_subdomain: str | None = None,
    days: list[date] | None = None,
    dry_run: bool = False,
    client_factory: Callable[[KapitalbankConnection], KapitalbankClient] = default_client_factory,
) -> RunReport:
    today = timezone.localtime(now).date()
    run_days = days_for(mode, today, days)
    if not _try_lock():
        logger.warning("kapitalbank: previous run still holds the lock; %s run skipped", mode)
        return RunReport(skipped_locked=True)
    try:
        report = RunReport()
        ctx = _Run(mode=mode, now=now, today=today, days=run_days, dry_run=dry_run, report=report)
        connections = KapitalbankConnection.objects.filter(is_enabled=True).select_related("tenant").order_by("tenant_id")
        if tenant_subdomain:
            connections = connections.filter(tenant__subdomain=tenant_subdomain)
        for conn in list(connections):
            try:
                _run_tenant(ctx, conn, client_factory)
            except Exception:
                logger.exception("kapitalbank: tenant_id=%s run failed", conn.tenant_id)
        logger.info(
            "kapitalbank: %s run%s done: ok=%s failed=%s created=%s alerts=%s",
            mode,
            " (dry run)" if dry_run else "",
            report.accounts_ok,
            report.accounts_failed,
            report.created,
            report.alerts,
        )
        return report
    finally:
        _unlock()


def _try_lock() -> bool:
    with db_connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [LOCK_ID])
        return bool(cursor.fetchone()[0])


def _unlock() -> None:
    try:
        with db_connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [LOCK_ID])
    except Exception:
        logger.exception("kapitalbank: failed to release the run lock")


def _linked(tenant) -> list[BankAccountLink]:
    return list(
        BankAccountLink.objects.filter(tenant=tenant, decision=BankAccountLink.LINKED)
        .select_related("tenant", "bank_account__wallet", "card_account__wallet")
        .order_by("id")
    )


def _run_tenant(ctx: _Run, conn: KapitalbankConnection, client_factory) -> None:
    tenant = conn.tenant
    try:
        password = conn.get_password() if conn.has_password else ""
    except Exception:
        logger.exception("kapitalbank: tenant_id=%s bank password cannot be read", tenant.pk)
        password = ""
    if not password:
        # Never send a request with an empty password (decrypt_secret returns "" on a bad key).
        logger.error("kapitalbank: tenant_id=%s bank password is not set or cannot be decrypted; skipped", tenant.pk)
        ctx.report.accounts_failed += len(_linked(tenant))
        if not ctx.dry_run:
            _event(
                tenant,
                None,
                SyncEvent.ERROR,
                "Пароль банка не задан или не расшифровывается: загрузка тенанта пропущена",
                payload={"mode": ctx.mode, "stage": "config"},
            )
        return
    secrets = _Secrets(conn.login, password)

    try:
        client = client_factory(conn)
    except Exception as exc:
        logger.exception("kapitalbank: tenant_id=%s client setup failed", tenant.pk)
        ctx.report.accounts_failed += len(_linked(tenant))
        if not ctx.dry_run:
            _event(
                tenant,
                None,
                SyncEvent.ERROR,
                f"Не удалось подключиться к банку: {_safe_message(exc, secrets)}",
                payload={"mode": ctx.mode, "stage": "client", "error_type": type(exc).__name__},
            )
        return

    if ctx.mode == "nightly" and not ctx.dry_run:
        try:
            refresh_account_list(conn, client, now=ctx.now)
        except Exception as exc:
            logger.exception("kapitalbank: tenant_id=%s account list refresh failed", tenant.pk)
            _event(
                tenant,
                None,
                SyncEvent.ERROR,
                f"Не удалось обновить список счетов: {_safe_message(exc, secrets)}",
                payload={
                    "mode": ctx.mode,
                    "stage": "account_list",
                    "code": _error_code(exc),
                    "error_type": type(exc).__name__,
                },
            )

    own_targets = {
        account_no.strip()
        for account_no in BankAccountLink.objects.filter(tenant=tenant, decision__in=_UNTRACKED).values_list(
            "account_no", flat=True
        )
    }
    for link in _linked(tenant):
        _run_link(ctx, link, client, own_targets, secrets)


def _run_link(ctx: _Run, link: BankAccountLink, client, own_targets: set[str], secrets: _Secrets) -> None:
    try:
        _load_link(ctx, link, client, own_targets)
    except Exception as exc:
        logger.exception("kapitalbank: account …%s (link_id=%s) failed", link.account_no[-4:], link.pk)
        ctx.report.accounts_failed += 1
        if not ctx.dry_run:
            _record_failure(ctx, link, exc, secrets)
        return
    ctx.report.accounts_ok += 1
    if not ctx.dry_run:
        _record_success(ctx, link)


def _load_link(ctx: _Run, link: BankAccountLink, client, own_targets: set[str]) -> None:
    today_statement: Statement | None = None
    for day in ctx.days:
        statement = _load_day(ctx, link, client, day, own_targets)
        if day == ctx.today:
            today_statement = statement
    if today_statement is not None and not ctx.dry_run:
        _reconcile(ctx, link, client, today_statement, own_targets)


def _load_day(
    ctx: _Run, link: BankAccountLink, client, day: date, own_targets: set[str], *, stage: str = "load"
) -> Statement:
    statement = client.get_statement(account_no=link.account_no, branch=link.branch, day=day)
    new_own_transfers = [] if ctx.dry_run else _new_own_transfers(link, statement, own_targets)
    result = ingest_statement(link, statement, dry_run=ctx.dry_run)
    ctx.report.created += result.created
    detail = {
        "tenant": link.tenant.subdomain,
        "account_no": link.account_no,
        "branch": link.branch,
        "day": day.isoformat(),
        "stage": stage,
        "saldo_out": str(_q(statement.saldo_out)),
        "created": result.created,
        "skipped_existing": result.skipped_existing,
        "would_create": result.would_create,
        "field_diffs": result.field_diffs,
        "missing_external_ids": [] if ctx.dry_run else list(result.missing_external_ids),
    }
    if ctx.dry_run and day == ctx.today:
        # Read-only preview of the reconciliation (portal balance before the would-be import).
        detail["portal_balance"] = str(_portal_balance(link))
    ctx.report.details.append(detail)
    if ctx.dry_run:
        return statement

    if result.created:
        _event(
            link.tenant,
            link,
            SyncEvent.IMPORTED,
            f"Загружено документов: {result.created}",
            day=day,
            payload={"created": result.created, "mode": ctx.mode, "stage": stage},
        )
    if result.missing_external_ids:
        _alert(
            ctx,
            kb_alerts.notify_missing_docs,
            link,
            day=day,
            external_ids=list(result.missing_external_ids),
            now=ctx.now,
        )
    for doc in new_own_transfers:
        _alert(ctx, kb_alerts.notify_own_transfer, link, doc, target_account=doc.acc_ct.strip())
    return statement


def _new_own_transfers(link: BankAccountLink, statement: Statement, own_targets: set[str]) -> list[StatementDoc]:
    """Outgoing docs to the tenant's own untracked/undecided account that are not yet in the portal."""
    if not own_targets:
        return []
    candidates: dict[str, StatementDoc] = {}
    for doc in statement.docs:
        if is_incoming(doc, link.account_no):
            continue
        if doc.acc_ct.strip() in own_targets:
            candidates.setdefault(str(doc.general_id), doc)
    if not candidates:
        return []
    present = existing_external_ids(link, set(candidates))
    return [doc for general_id, doc in candidates.items() if general_id not in present]


def _reconcile(ctx: _Run, link: BankAccountLink, client, today_statement: Statement, own_targets: set[str]) -> None:
    bank = _q(today_statement.saldo_out)
    portal = _portal_balance(link)
    if bank != portal:
        logger.info(
            "kapitalbank: account …%s balance differs (bank=%s portal=%s); re-fetching last %s days",
            link.account_no[-4:],
            bank,
            portal,
            NIGHTLY_DAYS_BACK,
        )
        for n in range(NIGHTLY_DAYS_BACK, 0, -1):
            _load_day(ctx, link, client, ctx.today - timedelta(days=n), own_targets, stage="recheck")
        today_statement = _load_day(ctx, link, client, ctx.today, own_targets, stage="recheck")
        bank = _q(today_statement.saldo_out)
        portal = _portal_balance(link)
    if bank != portal:
        _alert(ctx, kb_alerts.notify_mismatch, link, bank=bank, portal=portal, now=ctx.now)
    else:
        _alert(ctx, kb_alerts.notify_resolved, link, now=ctx.now)


def _portal_balance(link: BankAccountLink) -> Decimal:
    return _q(Decimal(str(wallet_balance_payload(wallet=link.wallet())["current_balance"])))


def _q(value) -> Decimal:
    return Decimal(value).quantize(_CENTS)


def _record_success(ctx: _Run, link: BankAccountLink) -> None:
    try:
        state, _ = AccountSyncState.objects.get_or_create(link=link)
        state.last_success_at = ctx.now
        state.consecutive_failures = 0
        state.save(update_fields=["last_success_at", "consecutive_failures"])
    except Exception:
        logger.exception("kapitalbank: link_id=%s success state not saved", link.pk)


def _record_failure(ctx: _Run, link: BankAccountLink, exc: Exception, secrets: _Secrets) -> None:
    code = _error_code(exc)
    message = _safe_message(exc, secrets)
    try:
        state, _ = AccountSyncState.objects.get_or_create(link=link)
        state.last_error_at = ctx.now
        state.last_error_code = code
        state.last_error_message = message
        state.consecutive_failures += 1
        state.save(update_fields=["last_error_at", "last_error_code", "last_error_message", "consecutive_failures"])
    except Exception:
        logger.exception("kapitalbank: link_id=%s failure state not saved", link.pk)
        return
    _event(
        link.tenant,
        link,
        SyncEvent.ERROR,
        message,
        payload={"code": code, "mode": ctx.mode, "error_type": type(exc).__name__},
    )
    last_success = state.last_success_at
    if last_success is None or ctx.now - last_success > DOWN_AFTER or ctx.mode == "nightly":
        _alert(ctx, kb_alerts.notify_down, link, code=code, message=message, now=ctx.now)


def _error_code(exc: Exception) -> int | None:
    return exc.code if isinstance(exc, KapitalbankError) else None


def _safe_message(exc: Exception, secrets: _Secrets) -> str:
    if isinstance(exc, KapitalbankError):
        text = str(exc.message)
    elif isinstance(exc, IngestError):
        text = f"Ошибка приёма выписки (HTTP {exc.status}): {exc.detail}"
    else:
        text = f"{type(exc).__name__}: {exc}"
    return secrets.redact(text)[:_MAX_MESSAGE]


def _event(tenant, link, kind: str, message: str, *, day: date | None = None, payload: dict | None = None) -> None:
    try:
        SyncEvent.objects.create(
            tenant=tenant, link=link, kind=kind, day=day, message=message, payload=payload or {}
        )
    except Exception:
        logger.exception("kapitalbank: %s event not saved tenant_id=%s", kind, getattr(tenant, "pk", None))


def _alert(ctx: _Run, notify, *args, **kwargs) -> bool:
    """Alerts run outside any transaction (ingest has already committed) and never fail the run."""
    try:
        sent = bool(notify(*args, **kwargs))
    except Exception:
        logger.exception("kapitalbank: alert %s failed", getattr(notify, "__name__", notify))
        return False
    if sent:
        ctx.report.alerts += 1
    return sent
