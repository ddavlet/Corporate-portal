"""Salary card payouts from the Kapitalbank payroll transit account (23106): load and store.

One run (hourly: yesterday and today; nightly: 40 days plus the bank's payroll directory;
manual: from --since):

1. Transit accounts: BankAccountLink rows on 23106… of tenants with a Kapitalbank connection.
   An account shared by several tenants (lemonfit / lemonhavo) is loaded once per day.
2. Rows: incoming dtype 21 = sheet (PayrollCardBatch), outgoing dtype 06 = card credit
   (PayrollCardPayout); create-only by (transit account, general_id or b2_id). Period = M−1.
3. Grouping by day and account, by sums only (the bank does not order ``content``): free card
   rows of a day go to the day's only sheet whose remainder they add up to.
4. Tenant of a sheet: the only tenant whose BankExpense has doc_no = sheet num, the same date and
   the same sum, among tenants that see the account (and the payer account, when a viewer has it
   linked); retried on every run. Free rows of a day whose sheets all belong to one tenant get that
   tenant only when the account is seen by that tenant alone or the rows add up to exactly what
   those sheets still miss.
5. Bank employees: GetWorkers1C and GetZP1C (nightly, or when a new row has an unknown card
   account) map card accounts to the bank's employee_id. Passport, INN, birth date are never
   read (client whitelist).
6. Rows without sheet or tenant for 2 days: SyncEvent + one Telegram alert to the owner
   (counts, sum and date only); rows paid before the 40-day window (manual backfill) are skipped.
7. card_payouts.attach_pending (and close_sweep at night).

The regular statement import (runner.py) is untouched: the transit account stays ignored there.
Errors are isolated per account, day and connection; texts never carry bank credentials or
personal data. Runs never overlap (advisory lock; cron adds flock).
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Callable, Literal

from django.db import IntegrityError, transaction
from django.db import connection as db_connection
from django.db.models import Exists, OuterRef, Q, Subquery, Sum
from django.utils import timezone

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.kapitalbank.alerts import format_amount, send_owner_alert
from apps.modules.kapitalbank.client import KapitalbankClient, KapitalbankError, Statement
from apps.modules.kapitalbank.models import BankAccountLink, KapitalbankConnection, SyncEvent
from apps.modules.payroll.card_balance import previous_month
from apps.modules.payroll.models import (
    BankPayrollEmployee,
    BankPayrollEmployeeAccount,
    PayrollCardBatch,
    PayrollCardPayout,
)

logger = logging.getLogger(__name__)

LOCK_ID = 7_301_027  # runner.LOCK_ID + 1: independent from the regular statement import
TRANSIT_PREFIX = "23106"
HOURLY_DAYS = 2
WINDOW_DAYS = 40
UNASSIGNED_AFTER = timedelta(days=2)
EVENT_SOURCE = "payroll_card"
_MAX_MESSAGE = 500
_NAME_RE = re.compile(r"сотрудник\w*\s+(.+?)[\s.,;]*$", re.IGNORECASE)

Mode = Literal["hourly", "nightly", "manual"]


@dataclass
class CardSyncReport:
    skipped_locked: bool = False
    accounts_ok: int = 0
    accounts_failed: int = 0
    batches_created: int = 0
    payouts_created: int = 0
    grouped: int = 0
    tenants_resolved: int = 0
    employees_matched: int = 0
    alerts: int = 0
    attached: int = 0
    closed: int = 0


def default_client_factory(conn: KapitalbankConnection) -> KapitalbankClient:
    return KapitalbankClient(conn.login, conn.get_password())


def days_for(mode: Mode, today: date, since: date | None = None) -> list[date]:
    if mode == "hourly":
        return [today - timedelta(days=n) for n in range(HOURLY_DAYS - 1, -1, -1)]
    if mode == "nightly":
        return [today - timedelta(days=n) for n in range(WINDOW_DAYS - 1, -1, -1)]
    if mode == "manual":
        if since is None or since > today:
            raise ValueError("manual mode requires since <= today")
        return [since + timedelta(days=n) for n in range((today - since).days + 1)]
    raise ValueError(f"Unknown mode: {mode!r}")


@dataclass
class _Transit:
    account_no: str
    branch: str
    connections: list[KapitalbankConnection] = field(default_factory=list)  # by tenant_id
    links: dict[int, BankAccountLink] = field(default_factory=dict)  # tenant_id -> link


@dataclass
class _Run:
    mode: Mode
    now: datetime
    today: date
    days: list[date]
    dry_run: bool
    report: CardSyncReport
    client_factory: Callable[[KapitalbankConnection], KapitalbankClient]
    clients: dict[int, KapitalbankClient | None] = field(default_factory=dict)  # connection pk -> client
    new_payout_ids: set[int] = field(default_factory=set)
    touched: set[tuple[str, date]] = field(default_factory=set)

    @property
    def window_start(self) -> date:
        return min(self.days[0], self.today - timedelta(days=WINDOW_DAYS - 1))


def sync(
    *,
    mode: Mode,
    now: datetime,
    since: date | None = None,
    tenant_subdomain: str | None = None,
    dry_run: bool = False,
    client_factory: Callable[[KapitalbankConnection], KapitalbankClient] = default_client_factory,
) -> CardSyncReport:
    today = timezone.localtime(now).date()
    days = days_for(mode, today, since)
    if not _try_lock():
        logger.warning("payroll card: previous sync still holds the lock; %s run skipped", mode)
        return CardSyncReport(skipped_locked=True)
    try:
        ctx = _Run(
            mode=mode, now=now, today=today, days=days, dry_run=dry_run, report=CardSyncReport(), client_factory=client_factory
        )
        if dry_run:
            with transaction.atomic():
                _run(ctx, tenant_subdomain)
                transaction.set_rollback(True)
        else:
            _run(ctx, tenant_subdomain)
        r = ctx.report
        logger.info(
            "payroll card: %s sync%s done: accounts_ok=%s failed=%s batches=%s payouts=%s grouped=%s "
            "tenants=%s matched=%s alerts=%s attached=%s closed=%s",
            mode, " (dry run)" if dry_run else "", r.accounts_ok, r.accounts_failed, r.batches_created,
            r.payouts_created, r.grouped, r.tenants_resolved, r.employees_matched, r.alerts, r.attached, r.closed,
        )
        return ctx.report
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
    except Exception as exc:
        logger.error("payroll card: failed to release the sync lock: %s", type(exc).__name__)


def _run(ctx: _Run, tenant_subdomain: str | None) -> None:
    # A dry run for one named tenant ignores is_enabled (preview before switching on), like runner.run.
    transits = _transit_accounts(tenant_subdomain, include_disabled=ctx.dry_run and bool(tenant_subdomain))
    for transit in transits:
        _load_transit(ctx, transit)
    _step(ctx, "directory", lambda c: _sync_directory(c, transits))
    _step(ctx, "group", _group_free_rows, atomic=True)
    _step(ctx, "tenant", _resolve_batch_tenants, atomic=True)
    _step(ctx, "day_tenant", _tenant_free_rows, atomic=True)
    if ctx.dry_run:
        return
    _step(ctx, "unassigned", lambda c: _report_unassigned(c, transits))
    # Local import: card_payouts pulls in payouts/services (requests, approvals).
    from apps.modules.payroll import card_payouts

    _step(ctx, "attach", lambda c: setattr(c.report, "attached", card_payouts.attach_pending(now=c.now)))
    if ctx.mode == "nightly":
        _step(ctx, "close_sweep", lambda c: setattr(c.report, "closed", card_payouts.close_sweep()))


def _step(ctx: _Run, name: str, fn, *, atomic: bool = False) -> None:
    """A failing stage is logged and does not stop the next ones. DB-only stages run in a savepoint
    (a failed statement must not break a dry run's outer transaction); attach and alerts do not, so
    document closes and Telegram messages are never held behind one long transaction."""
    try:
        if atomic:
            with transaction.atomic():
                fn(ctx)
        else:
            fn(ctx)
    except Exception as exc:
        logger.error("payroll card: stage %s failed: %s", name, type(exc).__name__)


# ── 1. transit accounts and statements ───────────────────────────────────────────────────────


def _transit_accounts(tenant_subdomain: str | None, *, include_disabled: bool) -> list[_Transit]:
    conns = KapitalbankConnection.objects.select_related("tenant").order_by("tenant_id")
    if not include_disabled:
        conns = conns.filter(is_enabled=True)
    if tenant_subdomain:
        conns = conns.filter(tenant__subdomain=tenant_subdomain)
    by_tenant = {conn.tenant_id: conn for conn in conns}
    transits: dict[tuple[str, str], _Transit] = {}
    links = BankAccountLink.objects.filter(
        tenant_id__in=list(by_tenant), account_no__startswith=TRANSIT_PREFIX
    ).order_by("tenant_id", "id")
    for link in links:
        transit = transits.setdefault((link.account_no, link.branch), _Transit(link.account_no, link.branch))
        transit.connections.append(by_tenant[link.tenant_id])
        transit.links[link.tenant_id] = link
    return list(transits.values())


def _client(ctx: _Run, conn: KapitalbankConnection, link: BankAccountLink | None) -> KapitalbankClient | None:
    if conn.pk in ctx.clients:
        return ctx.clients[conn.pk]
    client = None
    try:
        if not conn.has_password or not conn.get_password():
            raise KapitalbankError(None, "Пароль банка не задан или не расшифровывается")
        client = ctx.client_factory(conn)
    except Exception as exc:
        _error(ctx, conn, link, "client", exc)
    ctx.clients[conn.pk] = client
    return client


def _load_transit(ctx: _Run, transit: _Transit) -> None:
    failed_days = 0
    for day in ctx.days:
        loaded = False
        for conn in transit.connections:
            link = transit.links.get(conn.tenant_id)
            client = _client(ctx, conn, link)
            if client is None:
                continue
            try:
                statement = client.get_statement(account_no=transit.account_no, branch=transit.branch, day=day)
            except Exception as exc:
                _error(ctx, conn, link, "statement", exc, day=day)
                continue
            try:
                with transaction.atomic():
                    _store_statement(ctx, transit, day, statement)
            except Exception as exc:
                _error(ctx, conn, link, "store", exc, day=day)
                break  # the same statement would fail again through another connection
            loaded = True
            break
        if not loaded:
            failed_days += 1
    if failed_days:
        ctx.report.accounts_failed += 1
    else:
        ctx.report.accounts_ok += 1


def _doc_key(doc) -> str:
    return (doc.general_id or doc.b2_id or "").strip()


def name_from_purpose(purpose: str) -> str:
    """'Заработная плата за июль … сотруднику ISMOILOV SHERZOD' → 'ISMOILOV SHERZOD' (hint only)."""
    match = _NAME_RE.search(purpose or "")
    return match.group(1).strip()[:200] if match else ""


def _store_statement(ctx: _Run, transit: _Transit, day: date, statement: Statement) -> None:
    account = transit.account_no
    for doc in statement.docs:
        key = _doc_key(doc)
        dtype = (doc.dtype or "").lstrip("0")
        doc_day = doc.ddate or day
        if not key:
            logger.warning("payroll card: document without general_id/b2_id on …%s skipped", account[-4:])
            continue
        if dtype == "21" and doc.acc_ct == account and doc.acc_dt != account:
            _, created = PayrollCardBatch.objects.get_or_create(
                transit_account=account,
                bank_doc_key=key,
                defaults={
                    "transit_branch": transit.branch,
                    "num": doc.num.strip()[:50],
                    "doc_date": doc_day,
                    "amount": doc.amount,
                    "payer_account": doc.acc_dt[:20],
                    "purpose": doc.purpose,
                    "period_month": previous_month(doc_day),
                },
            )
            if created:
                ctx.report.batches_created += 1
                ctx.touched.add((account, doc_day))
        elif dtype == "6" and doc.acc_dt == account and doc.amount > 0:
            payout, created = PayrollCardPayout.objects.get_or_create(
                transit_account=account,
                bank_doc_key=key,
                defaults={
                    "card_account": doc.acc_ct[:20],
                    "amount": doc.amount,
                    "paid_on": doc_day,
                    "period_month": previous_month(doc_day),
                    "purpose": doc.purpose,
                    "name_from_purpose": name_from_purpose(doc.purpose),
                },
            )
            if created:
                ctx.report.payouts_created += 1
                ctx.new_payout_ids.add(payout.pk)
                ctx.touched.add((account, doc_day))


# ── 3–4. sheets and tenants ──────────────────────────────────────────────────────────────────


def _group_free_rows(ctx: _Run) -> None:
    """Free rows of a day join the day's only sheet whose remainder they add up to exactly
    (on the first pass: the only sheet of the day and the whole day's sum)."""
    days = set(ctx.touched) | set(
        PayrollCardPayout.objects.filter(batch__isnull=True, paid_on__gte=ctx.window_start)
        .values_list("transit_account", "paid_on")
        .distinct()
    )
    for account, day in sorted(days):
        try:
            with transaction.atomic():
                ctx.report.grouped += _group_day(account, day)
        except Exception as exc:
            logger.error("payroll card: grouping …%s %s failed: %s", account[-4:], day, type(exc).__name__)


def _group_day(account: str, day: date) -> int:
    free = list(
        PayrollCardPayout.objects.select_for_update()
        .filter(transit_account=account, paid_on=day, batch__isnull=True)
        .values_list("pk", "amount")
    )
    if not free:
        return 0
    free_sum = sum((amount for _, amount in free), Decimal("0"))
    incomplete = []
    for batch in PayrollCardBatch.objects.filter(transit_account=account, doc_date=day).order_by("id"):
        taken = PayrollCardPayout.objects.filter(batch=batch).aggregate(s=Sum("amount"))["s"] or Decimal("0")
        if taken < batch.amount:
            incomplete.append((batch, batch.amount - taken))
    if len(incomplete) != 1 or incomplete[0][1] != free_sum:
        return 0
    batch = incomplete[0][0]
    updates = {"batch": batch}
    if batch.tenant_id is not None:
        updates["tenant_id"] = batch.tenant_id
    return PayrollCardPayout.objects.filter(pk__in=[pk for pk, _ in free], batch__isnull=True).update(**updates)


def _resolve_batch_tenants(ctx: _Run) -> None:
    batches = PayrollCardBatch.objects.filter(tenant__isnull=True, doc_date__gte=ctx.window_start).order_by("id")
    for batch in batches:
        try:
            with transaction.atomic():
                if _resolve_batch_tenant(ctx, batch):
                    ctx.report.tenants_resolved += 1
        except Exception as exc:
            logger.error("payroll card: tenant of batch_id=%s not resolved: %s", batch.pk, type(exc).__name__)
    # Rows grouped into a sheet whose tenant is known take it.
    PayrollCardPayout.objects.filter(tenant__isnull=True, batch__tenant__isnull=False).update(
        tenant_id=Subquery(PayrollCardBatch.objects.filter(pk=OuterRef("batch_id")).values("tenant_id")[:1])
    )


def _resolve_batch_tenant(ctx: _Run, batch: PayrollCardBatch) -> bool:
    num = batch.num.strip()
    if not num:
        return False
    viewers = set(BankAccountLink.objects.filter(account_no=batch.transit_account).values_list("tenant_id", flat=True))
    if batch.payer_account:
        payers = set(
            BankAccountLink.objects.filter(account_no=batch.payer_account, tenant_id__in=viewers).values_list(
                "tenant_id", flat=True
            )
        )
        if payers:
            viewers = payers
    # Short payment numbers repeat: number and date alone may hit another tenant's expense, and the
    # sheet would then carry salaries (names) into that tenant. The sum must match too.
    expenses = BankExpense.objects.filter(
        tenant_id__in=viewers,
        doc_date=batch.doc_date,
        doc_no__in={num, num.lstrip("0") or num},
        debit_turnover=batch.amount,
    )
    tenant_ids = set(expenses.values_list("tenant_id", flat=True))
    if len(tenant_ids) != 1:
        if tenant_ids:
            logger.warning("payroll card: batch_id=%s matches bank expenses of several tenants; left without tenant", batch.pk)
        return False
    expense = expenses.order_by("id").first()
    batch.tenant_id = expense.tenant_id
    batch.bank_expense = expense
    batch.tenant_resolved_at = ctx.now
    batch.save(update_fields=["tenant", "bank_expense", "tenant_resolved_at"])
    PayrollCardPayout.objects.filter(batch=batch, tenant__isnull=True).update(tenant_id=expense.tenant_id)
    return True


def _tenant_free_rows(ctx: _Run) -> None:
    """Rows left without a sheet: when every sheet of that day and account belongs to one tenant,
    the rows get that tenant (the sheet stays unknown) — if the account is seen by that tenant alone,
    or the free rows add up to exactly what those sheets still miss. On a shared account another
    tenant's sheet may simply not have arrived, so otherwise the rows stay without a tenant (alert)."""
    days = (
        PayrollCardPayout.objects.filter(batch__isnull=True, tenant__isnull=True, paid_on__gte=ctx.window_start)
        .values_list("transit_account", "paid_on")
        .distinct()
    )
    for account, day in days:
        batches = list(PayrollCardBatch.objects.filter(transit_account=account, doc_date=day))
        tenant_ids = [batch.tenant_id for batch in batches]
        if not tenant_ids or None in tenant_ids or len(set(tenant_ids)) != 1:
            continue
        viewers = set(BankAccountLink.objects.filter(account_no=account).values_list("tenant_id", flat=True))
        if viewers != {tenant_ids[0]} and not _free_rows_fill_sheets(account, day, batches):
            continue
        PayrollCardPayout.objects.filter(
            transit_account=account, paid_on=day, batch__isnull=True, tenant__isnull=True
        ).update(tenant_id=tenant_ids[0])


def _free_rows_fill_sheets(account: str, day: date, batches: list[PayrollCardBatch]) -> bool:
    missing = Decimal("0")
    for batch in batches:
        taken = PayrollCardPayout.objects.filter(batch=batch).aggregate(s=Sum("amount"))["s"] or Decimal("0")
        missing += batch.amount - taken
    free = (
        PayrollCardPayout.objects.filter(transit_account=account, paid_on=day, batch__isnull=True).aggregate(
            s=Sum("amount")
        )["s"]
        or Decimal("0")
    )
    return free == missing


# ── 5. bank payroll directory ───────────────────────────────────────────────────────────────


def _match_accounts(ctx: _Run) -> int:
    account = BankPayrollEmployeeAccount.objects.filter(account_no=OuterRef("card_account"))
    matched = (
        PayrollCardPayout.objects.filter(bank_employee__isnull=True, employee_assigned_manually=False)
        .filter(Exists(account))
        .update(bank_employee_id=Subquery(account.values("bank_employee_id")[:1]))
    )
    ctx.report.employees_matched += matched
    return matched


def _unknown_rows(ctx: _Run):
    return PayrollCardPayout.objects.filter(
        bank_employee__isnull=True, employee_assigned_manually=False, paid_on__gte=ctx.window_start
    )


def _sync_directory(ctx: _Run, transits: list[_Transit]) -> None:
    _match_accounts(ctx)
    unknown = _unknown_rows(ctx)
    if ctx.mode == "hourly" and not unknown.filter(pk__in=ctx.new_payout_ids).exists():
        return
    by_conn: dict[int, tuple[KapitalbankConnection, set[str], BankAccountLink]] = {}
    for transit in transits:
        for conn in transit.connections:
            entry = by_conn.setdefault(conn.pk, (conn, set(), transit.links[conn.tenant_id]))
            entry[1].add(transit.account_no)
    done_clients: set[str] = set()
    for conn, accounts, link in by_conn.values():
        client = _client(ctx, conn, link)
        if client is None:
            continue
        try:
            bank_clients = client.list_clients()
        except Exception as exc:
            _error(ctx, conn, link, "directory", exc)
            continue
        # Only the organisations whose payroll project uses these transit accounts: a login may see
        # other companies, and their staff directory must not be loaded here.
        relevant = [c for c in bank_clients if {a for a, _ in c.payroll_accounts} & accounts]
        if not relevant:
            logger.warning(
                "payroll card: no bank client of tenant_id=%s pays through the transit account; directory skipped",
                conn.tenant_id,
            )
            continue
        sheet_days = sorted(
            set(unknown.filter(transit_account__in=accounts).values_list("paid_on", flat=True)) if ctx.mode != "hourly"
            else set(unknown.filter(pk__in=ctx.new_payout_ids, transit_account__in=accounts).values_list("paid_on", flat=True))
        )
        for bank_client in relevant:
            if not bank_client.client_id or bank_client.client_id in done_clients:
                continue
            done_clients.add(bank_client.client_id)
            _load_bank_client(ctx, conn, link, client, bank_client.client_id, sheet_days)
    _match_accounts(ctx)


def _load_bank_client(ctx: _Run, conn, link, client, client_id: str, sheet_days: list[date]) -> None:
    try:
        workers = client.list_payroll_workers(client_id=client_id)
    except Exception as exc:
        _error(ctx, conn, link, "workers", exc)
    else:
        for worker in workers:
            _upsert_bank_employee(
                ctx, client_id=client_id, external_id=worker.employee_id, full_name=worker.full_name,
                masked_card=worker.masked_card, branch=worker.branch, account_no=worker.account_no,
                source=BankPayrollEmployeeAccount.SOURCE_WORKERS,
            )
    for day in sheet_days:
        try:
            rows = client.get_payroll_sheets(client_id=client_id, day=day)
        except Exception as exc:
            _error(ctx, conn, link, "sheets", exc, day=day)
            continue
        for row in rows:
            _upsert_bank_employee(
                ctx, client_id=client_id, external_id=row.employee_id, full_name=row.full_name,
                masked_card="", branch="", account_no=row.account_no, source=BankPayrollEmployeeAccount.SOURCE_ZP,
            )


def _upsert_bank_employee(
    ctx: _Run, *, client_id: str, external_id: str, full_name: str, masked_card: str, branch: str, account_no: str, source: str
) -> None:
    if not external_id or not account_no:
        return
    try:
        with transaction.atomic():
            employee, created = BankPayrollEmployee.objects.get_or_create(
                bank_client_id=client_id[:32],
                external_id=external_id[:32],
                defaults={
                    "full_name": full_name[:200],
                    "masked_card": masked_card[:32],
                    "branch": branch[:5],
                    "first_seen_at": ctx.now,
                    "last_seen_at": ctx.now,
                },
            )
            if not created:
                updates = {"last_seen_at": ctx.now}
                # GetZP1C has no card: never blank out what GetWorkers1C gave.
                if full_name:
                    updates["full_name"] = full_name[:200]
                if masked_card:
                    updates["masked_card"] = masked_card[:32]
                if branch:
                    updates["branch"] = branch[:5]
                BankPayrollEmployee.objects.filter(pk=employee.pk).update(**updates)
            account, created = BankPayrollEmployeeAccount.objects.get_or_create(
                account_no=account_no[:20],
                defaults={"bank_employee": employee, "source": source, "first_seen_at": ctx.now, "last_seen_at": ctx.now},
            )
            if not created:
                if account.bank_employee_id != employee.pk:
                    logger.warning(
                        "payroll card: card account …%s already belongs to bank_employee_id=%s, kept",
                        account_no[-4:], account.bank_employee_id,
                    )
                else:
                    BankPayrollEmployeeAccount.objects.filter(pk=account.pk).update(last_seen_at=ctx.now)
    except Exception as exc:
        logger.error("payroll card: bank employee not saved: %s", type(exc).__name__)


# ── 6. rows nobody can see ──────────────────────────────────────────────────────────────────


def _report_unassigned(ctx: _Run, transits: list[_Transit]) -> None:
    owners = {t.account_no: (t.connections[0], t.links[t.connections[0].tenant_id]) for t in transits if t.connections}
    rows = (
        PayrollCardPayout.objects.filter(
            unassigned_alerted_at__isnull=True,
            created_at__lte=ctx.now - UNASSIGNED_AFTER,
            # A manual backfill (--since) stores old rows with today's created_at: no alert per old day.
            paid_on__gte=ctx.today - timedelta(days=WINDOW_DAYS - 1),
        )
        .filter(Q(batch__isnull=True) | Q(tenant__isnull=True))
        .order_by("transit_account", "paid_on", "bank_doc_key")
        .values_list("pk", "transit_account", "paid_on", "bank_doc_key", "amount")
    )
    groups: dict[tuple[str, date], list[tuple]] = defaultdict(list)
    for row in rows:
        groups[(row[1], row[2])].append(row)
    for (account, day), items in groups.items():
        owner = owners.get(account)
        if owner is None:
            continue  # the account is not loaded by this run (other tenant / connection off)
        conn, link = owner
        dedup_key = f"payroll_card_unassigned:{account}:{items[0][3]}"[:255]
        total = sum((item[4] for item in items), Decimal("0"))
        ids = [item[0] for item in items]
        if not SyncEvent.objects.filter(dedup_key=dedup_key).exists():
            text = (
                f"⚠️ Выплаты ЗП на карты не разобраны 2 дня: {len(items)} шт. на {format_amount(total)} "
                f"за {day:%d.%m.%Y} (транзитный счёт …{account[-4:]}): не найдены ведомость или тенант. "
                "Проверьте раздел «Выплаты ЗП на карту» в админке."
            )
            payload = {"source": EVENT_SOURCE, "day": day.isoformat(), "rows": len(items), "amount": str(total)}
            try:
                sent = send_owner_alert(
                    text, tenant=conn.tenant, link=link, kind=SyncEvent.MISSING_DOCS, dedup_key=dedup_key, payload=payload
                )
            except Exception as exc:
                logger.error("payroll card: unassigned alert failed: %s", type(exc).__name__)
                continue
            if not sent:
                continue
            ctx.report.alerts += 1
        PayrollCardPayout.objects.filter(pk__in=ids).update(unassigned_alerted_at=ctx.now)


# ── errors ──────────────────────────────────────────────────────────────────────────────────


def _error(ctx: _Run, conn: KapitalbankConnection, link, stage: str, exc: Exception, *, day: date | None = None) -> None:
    """One ERROR SyncEvent per tenant, stage, account and day of the run; never secrets or personal data."""
    code = exc.code if isinstance(exc, KapitalbankError) else None
    text = str(exc.message) if isinstance(exc, KapitalbankError) else type(exc).__name__
    account = getattr(link, "account_no", "") or ""
    logger.warning(
        "payroll card: %s failed tenant_id=%s account=…%s day=%s: %s",
        stage, conn.tenant_id, account[-4:], day, text,
    )
    dedup_key = f"payroll_card_error:{conn.tenant_id}:{stage}:{account}:{ctx.today.isoformat()}"[:255]
    try:
        if SyncEvent.objects.filter(dedup_key=dedup_key).exists():
            return
        with transaction.atomic():
            SyncEvent.objects.create(
                tenant_id=conn.tenant_id,
                link=link,
                kind=SyncEvent.ERROR,
                day=day,
                message=f"Выплаты ЗП на карты ({stage}): {text}"[:_MAX_MESSAGE],
                payload={"source": EVENT_SOURCE, "mode": ctx.mode, "stage": stage, "code": code, "error_type": type(exc).__name__},
                dedup_key=dedup_key,
            )
    except IntegrityError:
        pass
    except Exception as save_exc:
        logger.error("payroll card: error event not saved: %s", type(save_exc).__name__)
