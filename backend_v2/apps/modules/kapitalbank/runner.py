"""One Kapitalbank import run: daytime (today), nightly (account list + today + last 5 days), manual.

The nightly run attaches an account the bank lists for the first time right away (by its kind,
tracked from today, so it is loaded the same night) and tells the owner about it.

Per enabled tenant and per LINKED account: fetch the statement of every day, create the
missing rows (ingest is create-only and atomic per call), then alert. Alerts are sent
outside any transaction and never fail the run. Today's balance is reconciled only after
a self-heal re-fetch of the last days, so a back-dated document is not a false alarm.

Every failure is isolated to its day, account or tenant and recorded; the bank login and
password (and their Basic-auth token) never reach logs, SyncEvent rows or alert texts.
Runs never overlap: a global Postgres advisory lock is held for the whole run.
"""

from __future__ import annotations

import base64
import logging
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Callable, Literal

from django.db import IntegrityError, transaction
from django.db import connection as db_connection
from django.utils import timezone

from apps.modules.wallets.models import BankAccount, Wallet
from apps.modules.wallets.services import wallet_balance_payload

from . import alerts as kb_alerts
from .accounts import refresh_account_list
from .classification import AutoAttachResult, auto_attach_new, kind_for_account
from .client import KapitalbankClient, KapitalbankError, Statement, StatementDoc
from .ingest import IngestError, ingest_statement, present_on_wallet
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
_SERVICE = BankAccount.AccountType.SERVICE


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


class _Secrets:
    """Bank credentials seen during the run; redacted from every text we log, store or send."""

    def __init__(self):
        self._values: set[str] = set()

    def add(self, login: str, password: str) -> None:
        for value in (login, password):
            if value:
                self._values.add(value)
        if password:
            # The exact token KapitalbankClient puts in the Basic auth header.
            self._values.add(base64.b64encode(f"{login}:{password}".encode()).decode())

    def redact(self, text: str) -> str:
        for value in sorted(self._values, key=len, reverse=True):
            text = text.replace(value, "***")
        return text


@dataclass
class _Run:
    mode: Mode
    now: datetime
    today: date
    days: list[date]
    dry_run: bool
    report: RunReport
    secrets: _Secrets
    processed: set[int] = field(default_factory=set)  # link ids already counted ok/failed


def _log_error(secrets: _Secrets, msg: str, *args) -> None:
    """logger.exception replacement: call inside `except`; the traceback is redacted."""
    logger.error(msg + ": %s", *args, secrets.redact(traceback.format_exc()))


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
    secrets = _Secrets()
    if not _try_lock():
        logger.warning("kapitalbank: previous run still holds the lock; %s run skipped", mode)
        return RunReport(skipped_locked=True)
    try:
        report = RunReport()
        ctx = _Run(mode=mode, now=now, today=today, days=run_days, dry_run=dry_run, report=report, secrets=secrets)
        # A dry run for one named tenant ignores is_enabled, so the cutover can be previewed
        # before the import is switched on; it still loads only LINKED accounts.
        for conn in _enabled_connections(tenant_subdomain, include_disabled=dry_run and bool(tenant_subdomain)):
            try:
                _run_tenant(ctx, conn, client_factory)
            except Exception as exc:
                _log_error(secrets, "kapitalbank: tenant_id=%s run failed", conn.tenant_id)
                _fail_tenant(ctx, conn, "tenant", f"Сбой загрузки тенанта: {_safe_message(ctx, exc)}", exc)
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
        _unlock(secrets)


@dataclass
class RefreshReport:
    skipped_locked: bool = False
    links: list[BankAccountLink] = field(default_factory=list)
    error: str = ""  # redacted, safe to print


def refresh_accounts(
    *,
    tenant_subdomain: str,
    now: datetime,
    client_factory: Callable[[KapitalbankConnection], KapitalbankClient] = default_client_factory,
) -> RefreshReport:
    """Cutover helper: refresh one tenant's bank account list regardless of is_enabled.

    Writes only BankAccountLink rows (new ones PENDING, decisions untouched); loads no
    statements, records no SyncEvent and sends no alert. Holds the run lock like a run.
    """
    secrets = _Secrets()
    if not _try_lock():
        logger.warning("kapitalbank: previous run still holds the lock; account list refresh skipped")
        return RefreshReport(skipped_locked=True)
    try:
        conn = KapitalbankConnection.objects.select_related("tenant").filter(tenant__subdomain=tenant_subdomain).first()
        if conn is None:
            return RefreshReport(error=f"Подключение Капиталбанк для тенанта {tenant_subdomain} не найдено")
        password = _read_password(secrets, conn)
        secrets.add(conn.login, password)
        if not password:
            return RefreshReport(error="Пароль банка не задан или не расшифровывается")
        try:
            links = refresh_account_list(conn, client_factory(conn), now=now)
        except Exception as exc:
            _log_error(secrets, "kapitalbank: tenant_id=%s manual account list refresh failed", conn.tenant_id)
            return RefreshReport(error=f"Не удалось обновить список счетов: {_safe_text(secrets, exc)}")
        logger.info("kapitalbank: tenant_id=%s account list refreshed: %s accounts", conn.tenant_id, len(links))
        return RefreshReport(links=links)
    finally:
        _unlock(secrets)


def _try_lock() -> bool:
    with db_connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [LOCK_ID])
        return bool(cursor.fetchone()[0])


def _unlock(secrets: _Secrets) -> None:
    try:
        with db_connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [LOCK_ID])
    except Exception:
        _log_error(secrets, "kapitalbank: failed to release the run lock")


def _enabled_connections(tenant_subdomain: str | None, *, include_disabled: bool = False) -> list[KapitalbankConnection]:
    qs = KapitalbankConnection.objects.select_related("tenant").order_by("tenant_id")
    if not include_disabled:
        qs = qs.filter(is_enabled=True)
    if tenant_subdomain:
        qs = qs.filter(tenant__subdomain=tenant_subdomain)
    return list(qs)


def _linked(tenant) -> list[BankAccountLink]:
    """LINKED accounts to load; those whose portal account is a service one are not loaded
    (card links have no bank_account and stay included)."""
    return list(
        BankAccountLink.objects.filter(tenant=tenant, decision=BankAccountLink.LINKED)
        .exclude(bank_account__account_type=_SERVICE)
        .select_related("tenant", "bank_account__wallet", "card_account__wallet")
        .order_by("id")
    )


def _own_targets(tenant) -> set[str]:
    """The tenant's own accounts whose statements are not loaded: undecided, ignored, and
    LINKED to a service account. A transfer to one of them is alerted."""
    untracked = BankAccountLink.objects.filter(tenant=tenant, decision__in=_UNTRACKED).values_list(
        "account_no", flat=True
    )
    service = BankAccountLink.objects.filter(
        tenant=tenant, decision=BankAccountLink.LINKED, bank_account__account_type=_SERVICE
    ).values_list("account_no", flat=True)
    return {account_no.strip() for account_no in [*untracked, *service]}


def _tracked(link: BankAccountLink, day: date) -> bool:
    """Days before the link's tracking start are skipped silently (no load, no event)."""
    return link.track_from is None or day >= link.track_from


def _read_password(secrets: _Secrets, conn: KapitalbankConnection) -> str:
    try:
        return conn.get_password() if conn.has_password else ""
    except Exception:
        _log_error(secrets, "kapitalbank: tenant_id=%s bank password cannot be read", conn.tenant_id)
        return ""


def _run_tenant(ctx: _Run, conn: KapitalbankConnection, client_factory) -> None:
    tenant = conn.tenant
    password = _read_password(ctx.secrets, conn)
    ctx.secrets.add(conn.login, password)
    if not password:
        # Never send a request with an empty password (decrypt_secret returns "" on a bad key).
        logger.error("kapitalbank: tenant_id=%s bank password is not set or cannot be decrypted; skipped", tenant.pk)
        _fail_tenant(ctx, conn, "config", "Пароль банка не задан или не расшифровывается: загрузка тенанта пропущена")
        return

    try:
        client = client_factory(conn)
    except Exception as exc:
        _log_error(ctx.secrets, "kapitalbank: tenant_id=%s client setup failed", tenant.pk)
        _fail_tenant(ctx, conn, "client", f"Не удалось подключиться к банку: {_safe_message(ctx, exc)}", exc)
        return

    if ctx.mode == "nightly" and not ctx.dry_run:
        try:
            listed = refresh_account_list(conn, client, now=ctx.now)
        except Exception as exc:
            _log_error(ctx.secrets, "kapitalbank: tenant_id=%s account list refresh failed", tenant.pk)
            message = _safe_message(ctx, exc)
            _tenant_event(
                ctx,
                tenant,
                "account_list",
                f"Не удалось обновить список счетов: {message}",
                payload={"code": _error_code(exc), "error_type": type(exc).__name__},
            )
            _alert(ctx, kb_alerts.notify_accounts_refresh_failed, tenant, message=message, today=ctx.today, now=ctx.now)
        else:
            _attach_new_accounts(ctx, listed)

    own_targets = _own_targets(tenant)
    for link in _linked(tenant):
        ctx.processed.add(link.pk)
        _run_link(ctx, link, client, own_targets)


def _attach_new_accounts(ctx: _Run, listed: list[BankAccountLink]) -> None:
    """Accounts this refresh created (PENDING, first seen now) are attached by kind and alerted;
    one that cannot be attached stays PENDING and the alert says why. Never stops the run."""
    for link in listed:
        if link.decision != BankAccountLink.PENDING or link.first_seen_at != ctx.now:
            continue
        try:
            outcome = auto_attach_new(link, today=ctx.today, now=ctx.now)
        except Exception:
            _log_error(ctx.secrets, "kapitalbank: new account …%s (link_id=%s) not attached", link.account_no[-4:], link.pk)
            try:
                link.refresh_from_db()  # the attach rolled back; drop its in-memory decision
            except Exception:
                _log_error(ctx.secrets, "kapitalbank: link_id=%s cannot be re-read", link.pk)
            outcome = AutoAttachResult(
                kind_for_account(link.account_no, link.currency), "внутренняя ошибка портала (подробности в журнале)"
            )
        _alert(ctx, kb_alerts.notify_new_account, link, kind=outcome.kind, problem=outcome.problem, now=ctx.now)


def _fail_tenant(ctx: _Run, conn: KapitalbankConnection, stage: str, message: str, exc: Exception | None = None) -> None:
    """Tenant-level failure: one SyncEvent per day and cause, and every not-yet-processed
    LINKED account of the tenant is failed (state + down alert), so the owner learns of it."""
    try:
        links = [link for link in _linked(conn.tenant) if link.pk not in ctx.processed]
    except Exception:
        _log_error(ctx.secrets, "kapitalbank: tenant_id=%s linked accounts cannot be read", conn.tenant_id)
        links = []
    ctx.report.accounts_failed += len(links)
    ctx.processed.update(link.pk for link in links)
    if ctx.dry_run:
        return
    payload = {"error_type": type(exc).__name__} if exc is not None else {}
    _tenant_event(ctx, conn.tenant, stage, message, payload=payload)
    for link in links:
        _mark_failed(ctx, link, code=None, message=message)


def _tenant_event(ctx: _Run, tenant, stage: str, message: str, *, payload: dict | None = None) -> None:
    dedup_key = f"tenant_error:{tenant.pk}:{stage}:{ctx.today.isoformat()}"
    try:
        if SyncEvent.objects.filter(dedup_key=dedup_key).exists():
            return
        with transaction.atomic():
            SyncEvent.objects.create(
                tenant=tenant,
                link=None,
                kind=SyncEvent.ERROR,
                message=message,
                payload={"mode": ctx.mode, "stage": stage, **(payload or {})},
                dedup_key=dedup_key,
            )
    except IntegrityError:
        pass  # already recorded today
    except Exception:
        _log_error(ctx.secrets, "kapitalbank: tenant_id=%s error event not saved", tenant.pk)


def _run_link(ctx: _Run, link: BankAccountLink, client, own_targets: set[str]) -> None:
    try:
        failures = _load_link(ctx, link, client, own_targets)
    except Exception as exc:
        _log_error(ctx.secrets, "kapitalbank: account …%s (link_id=%s) failed", link.account_no[-4:], link.pk)
        failures = [(None, exc)]
    if not failures:
        ctx.report.accounts_ok += 1
        if not ctx.dry_run:
            _record_success(ctx, link)
        return
    ctx.report.accounts_failed += 1
    if not ctx.dry_run:
        _record_failures(ctx, link, failures)


def _ordered_days(ctx: _Run) -> list[date]:
    if ctx.mode != "nightly":
        return list(ctx.days)
    # Today first, so a broken past day never delays today's load and reconciliation.
    past = sorted((d for d in ctx.days if d != ctx.today), reverse=True)
    return ([ctx.today] if ctx.today in ctx.days else []) + past


def _load_link(ctx: _Run, link: BankAccountLink, client, own_targets: set[str]) -> list[tuple[date | None, Exception]]:
    failures: list[tuple[date | None, Exception]] = []
    today: tuple[Statement, dict] | None = None
    for day in _ordered_days(ctx):
        if not _tracked(link, day):
            continue
        try:
            loaded = _load_day(ctx, link, client, day, own_targets)
        except Exception as exc:
            _log_error(ctx.secrets, "kapitalbank: account …%s day %s failed", link.account_no[-4:], day)
            failures.append((day, exc))
            continue
        if day == ctx.today:
            today = loaded
    if today is not None and not ctx.dry_run:
        try:
            _reconcile(ctx, link, client, *today, own_targets, failures)
        except Exception as exc:
            _log_error(ctx.secrets, "kapitalbank: account …%s reconciliation failed", link.account_no[-4:])
            failures.append((ctx.today, exc))
    return failures


def _load_day(
    ctx: _Run, link: BankAccountLink, client, day: date, own_targets: set[str], *, stage: str = "load"
) -> tuple[Statement, dict]:
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
        "saldo_out": None if statement.saldo_out is None else str(_q(statement.saldo_out)),
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
        return statement, detail

    if day == link.track_from and link.opening_synced_at is None:
        _sync_opening_balance(ctx, link, statement)
    if result.created:
        _event(
            ctx,
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
    return statement, detail


def _sync_opening_balance(ctx: _Run, link: BankAccountLink, statement: Statement) -> None:
    """Once per link: the bank's saldo_in of the tracking start day becomes the wallet's opening
    balance, so the portal balance (opening + loaded movements) matches the bank from day one."""
    wallet = link.wallet()
    with transaction.atomic():
        Wallet.objects.filter(pk=wallet.pk).update(opening_balance=statement.saldo_in)
        BankAccountLink.objects.filter(pk=link.pk).update(opening_synced_at=ctx.now)
    # The reconciliation and later days of this run read these same objects.
    wallet.refresh_from_db(fields=["opening_balance"])
    link.refresh_from_db(fields=["opening_synced_at"])
    logger.info(
        "kapitalbank: account …%s opening balance set from bank saldo_in of %s",
        link.account_no[-4:],
        link.track_from,
    )


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
    # All candidates are outgoing: only the expense model is looked at (a transfer between our own
    # accounts is a revenue on the other one with the same general_id), including n8n's expense
    # rows without external_id.
    present = present_on_wallet(link, candidates)
    return [doc for general_id, doc in candidates.items() if general_id not in present]


def _reconcile(
    ctx: _Run,
    link: BankAccountLink,
    client,
    statement: Statement,
    detail: dict,
    own_targets: set[str],
    failures: list,
) -> None:
    if statement.saldo_out is None:
        _skip_reconcile(link, detail, "no saldo_out in today's statement")
        return
    bank = _q(statement.saldo_out)
    portal = _portal_balance(link)
    if bank != portal:
        logger.info(
            "kapitalbank: account …%s balance differs (bank=%s portal=%s); re-fetching last %s days",
            link.account_no[-4:],
            bank,
            portal,
            NIGHTLY_DAYS_BACK,
        )
        recheck_failed = False
        for n in range(NIGHTLY_DAYS_BACK, 0, -1):
            day = ctx.today - timedelta(days=n)
            if not _tracked(link, day):
                continue
            try:
                _load_day(ctx, link, client, day, own_targets, stage="recheck")
            except Exception as exc:
                _log_error(ctx.secrets, "kapitalbank: account …%s recheck day %s failed", link.account_no[-4:], day)
                failures.append((day, exc))
                recheck_failed = True
        statement, detail = _load_day(ctx, link, client, ctx.today, own_targets, stage="recheck")
        if recheck_failed:
            # Unverified: the missing document may be in the day that failed. The account is
            # recorded as failed, and a lasting failure reaches the owner as a down alert.
            _skip_reconcile(link, detail, "re-fetch of a past day failed")
            return
        if statement.saldo_out is None:
            _skip_reconcile(link, detail, "no saldo_out in today's statement")
            return
        bank = _q(statement.saldo_out)
        portal = _portal_balance(link)
    if bank != portal:
        detail["reconcile"] = "mismatch"
        _alert(ctx, kb_alerts.notify_mismatch, link, bank=bank, portal=portal, now=ctx.now)
    else:
        detail["reconcile"] = "match"
        _alert(ctx, kb_alerts.notify_resolved, link, now=ctx.now)


def _skip_reconcile(link: BankAccountLink, detail: dict, reason: str) -> None:
    logger.warning("kapitalbank: account …%s balance check skipped: %s", link.account_no[-4:], reason)
    detail["reconcile"] = f"skipped: {reason}"


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
        _log_error(ctx.secrets, "kapitalbank: link_id=%s success state not saved", link.pk)


def _record_failures(ctx: _Run, link: BankAccountLink, failures: list[tuple[date | None, Exception]]) -> None:
    for day, exc in failures:
        _event(
            ctx,
            link.tenant,
            link,
            SyncEvent.ERROR,
            _safe_message(ctx, exc),
            day=day,
            payload={"code": _error_code(exc), "mode": ctx.mode, "error_type": type(exc).__name__},
        )
    _, first = failures[0]
    _mark_failed(ctx, link, code=_error_code(first), message=_safe_message(ctx, first))


def _mark_failed(ctx: _Run, link: BankAccountLink, *, code: int | None, message: str) -> None:
    try:
        state, _ = AccountSyncState.objects.get_or_create(link=link)
        state.last_error_at = ctx.now
        state.last_error_code = code
        state.last_error_message = message
        state.consecutive_failures += 1
        state.save(update_fields=["last_error_at", "last_error_code", "last_error_message", "consecutive_failures"])
    except Exception:
        _log_error(ctx.secrets, "kapitalbank: link_id=%s failure state not saved", link.pk)
        return
    if _down_due(ctx, state):
        _alert(ctx, kb_alerts.notify_down, link, code=code, message=message, now=ctx.now)


def _down_due(ctx: _Run, state: AccountSyncState) -> bool:
    if ctx.mode == "nightly":
        return True
    last_success = state.last_success_at
    return state.consecutive_failures >= 2 and (last_success is None or ctx.now - last_success > DOWN_AFTER)


def _error_code(exc: Exception) -> int | None:
    return exc.code if isinstance(exc, KapitalbankError) else None


def _safe_message(ctx: _Run, exc: Exception) -> str:
    return _safe_text(ctx.secrets, exc)


def _safe_text(secrets: _Secrets, exc: Exception) -> str:
    if isinstance(exc, KapitalbankError):
        text = str(exc.message)
    elif isinstance(exc, IngestError):
        text = f"Ошибка приёма выписки (HTTP {exc.status}): {exc.detail}"
    else:
        text = f"{type(exc).__name__}: {exc}"
    return secrets.redact(text)[:_MAX_MESSAGE]


def _event(ctx: _Run, tenant, link, kind: str, message: str, *, day: date | None = None, payload: dict | None = None) -> None:
    try:
        SyncEvent.objects.create(tenant=tenant, link=link, kind=kind, day=day, message=message, payload=payload or {})
    except Exception:
        _log_error(ctx.secrets, "kapitalbank: %s event not saved tenant_id=%s", kind, getattr(tenant, "pk", None))


def _alert(ctx: _Run, notify, *args, **kwargs) -> bool:
    """Alerts run outside any transaction (ingest has already committed) and never fail the run."""
    try:
        sent = bool(notify(*args, **kwargs))
    except Exception:
        _log_error(ctx.secrets, "kapitalbank: alert %s failed", getattr(notify, "__name__", "?"))
        return False
    if sent:
        ctx.report.alerts += 1
    return sent
