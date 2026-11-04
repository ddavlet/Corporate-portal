"""Weekly investor report: metrics, text (vs the n8n draft), cron command and API.

Reference texts (A1/A2/O1/O2/H2/A_JAN) were produced by the n8n Code node «Собрать отчёты»
of workflow invReportAllTnt1 (buildReports) on exactly the fixture data below; the portal must
reproduce them character for character.
"""

import datetime as dt
from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APITestCase

from apps.modules.cash_withdrawals.fixtures import GATEWAY_PATH, gateway_ok
from apps.modules.investments.investor_report import (
    InvestorReportError,
    ReportRow,
    ReportSettings,
    build_investor_report,
    compute_investor_report,
)
from apps.modules.investments.investor_report_formatter import format_investor_report
from apps.modules.investments.investor_report_jobs import process_due_reports
from apps.modules.investments.models import (
    CbuExchangeRate,
    InvestReportConfig,
    InvestReportDispatch,
    InvestReturn,
    ProjectInvestment,
)
from apps.modules.investments.services import usd_uzs_rate_on_or_before
from apps.modules.telegram_approvals.models import TelegramMessage, TenantTelegramChat
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()
TZ = ZoneInfo("Asia/Tashkent")
NBSP = " "

RATES = [("2025-12-30", "12100.50"), ("2026-01-15", "12700.00"), ("2026-05-08", "12650.25"), ("2026-09-01", "12500.00")]

# Same data the n8n draft was run on: (date, amount, currency, confirmed) and
# (date, billing_date, sum, currency, confirmed, type, recipient).
TENANT_DATA = {
    "lemonaqua": {
        "name": "Lemonfit AQUA",
        "target": Decimal("34.72"),
        "start_month": None,
        "investments": [
            ("2025-06-01", "600000000.00", "UZS", True),  # before the rate archive → earliest rate
            ("2025-11-20", "250000.00", "USD", True),
            ("2026-01-15", "1270000000.00", "UZS", True),  # first investment of the year → period from February
            ("2026-10-20", "20000.00", "USD", False),
        ],
        "returns": [
            ("2026-01-10", "2025-12-01", "9000.00", "USD", True, "доля_прибыли", "инвестор"),
            ("2026-03-05", "2026-02-01", "10500.50", "USD", True, "доля_прибыли", "инвестор"),
            ("2026-04-06", "2026-03-01", "11200.00", "USD", True, "доля_прибыли", "инвестор"),
            ("2026-05-10", "2026-04-01", "139153000.00", "UZS", True, "доля_прибыли", "инвестор"),  # Sunday → Friday rate
            ("2026-06-05", "2026-05-01", "9800.00", "USD", True, "доля_прибыли", "инвестор"),
            ("2026-07-07", "2026-06-01", "12000.00", "USD", True, "доля_прибыли", "инвестор"),
            ("2026-08-06", "2026-07-01", "10000.00", "USD", True, "тело_инвестиций", "инвестор"),
            ("2026-09-08", "2026-08-01", "11500.00", "USD", True, "доля_прибыли", "инвестор"),
            ("2026-09-08", "2026-08-01", "4000.00", "USD", True, "доля_прибыли", "партнер"),
            ("2026-10-22", "2026-09-01", "3000.00", "USD", False, "доля_прибыли", "инвестор"),
        ],
    },
    "lemonfit": {
        "name": "Lemonfit ONE",
        "target": Decimal("21.40"),
        "start_month": 2,
        "investments": [
            ("2024-09-01", "300000.00", "USD", True),
            ("2026-02-10", "6350000000.00", "UZS", False),
            ("2026-03-02", "50000.00", "USD", True),
        ],
        "returns": [
            ("2026-03-03", "2026-02-01", "8000.00", "USD", True, "доля_прибыли", "инвестор"),
            ("2026-04-03", "2026-03-01", "8000.00", "USD", True, "доля_прибыли", "инвестор"),
            ("2026-05-04", "2026-04-01", "8000.00", "USD", True, "доля_прибыли", "инвестор"),
            ("2026-06-03", "2026-05-01", "8000.00", "USD", True, "доля_прибыли", "инвестор"),
            ("2026-07-03", "2026-06-01", "8000.00", "USD", True, "доля_прибыли", "инвестор"),
            ("2026-08-03", "2026-07-01", "8000.00", "USD", True, "доля_прибыли", "инвестор"),
            ("2026-09-03", "2026-08-01", "8000.00", "USD", True, "доля_прибыли", "инвестор"),
            ("2026-10-21", "2026-10-01", "5000.00", "USD", True, "тело_инвестиций", "инвестор"),
        ],
    },
    "lemonhavo": {
        "name": "Lemon HAVO",
        "target": None,
        "start_month": None,
        "investments": [
            ("2026-05-20", "150000.00", "USD", True),
            ("2026-06-15", "1265025000.00", "UZS", True),
        ],
        "returns": [],
    },
}

# n8n invReportAllTnt1, lemonaqua, today=2026-10-23
A1 = (
    "📊 <b>Lemonfit AQUA</b> · 23.10.2026\n"
    "\n"
    "💰 Вложено всего: <b>399\u00a0585\u00a0$</b> (+20\u00a0000\u00a0$ на согласовании)\n"
    "💵 Выплачено всего: <b>85\u00a0001\u00a0$</b> (+3\u00a0000\u00a0$ на согласовании)\n"
    "\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0за 2026 год: 76\u00a0001\u00a0$\n"
    "\n"
    "📈 Доходность сейчас: 2,38% в мес. · <b>28,5% годовых</b>\n"
    "\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0без учёта сентября: 2,72% в мес. · <b>32,6% годовых</b>\n"
    "🎯 Целевая: 2,89% в мес. · <b>34,7% годовых</b>\n"
    "⚠️ Отставание: −0,52\u00a0п.п. в мес. · <b>−6,2\u00a0п.п. годовых</b>\n"
    "\n"
    "📅 <b>По плану на сегодня</b> (февраль–сентябрь):\n"
    "Должно быть выплачено: 92\u00a0491\u00a0$\n"
    "Выплачено: 76\u00a0001\u00a0$\n"
    "🔻 Дефицит: <b>16\u00a0490\u00a0$</b> (+3\u00a0000\u00a0$ на согласовании)\n"
    "\n"
    "🧾 <b>Последние выплаты:</b>\n"
    "08.09 — 11\u00a0500\u00a0$ · доля прибыли за август\n"
    "06.08 — 10\u00a0000\u00a0$ · тело инвестиций за июль\n"
    "07.07 — 12\u00a0000\u00a0$ · доля прибыли за июнь"
)

# n8n invReportAllTnt1, lemonfit, today=2026-10-23
O1 = (
    "📊 <b>Lemonfit ONE</b> · 23.10.2026\n"
    "\n"
    "💰 Вложено всего: <b>350\u00a0000\u00a0$</b> (+500\u00a0000\u00a0$ на согласовании)\n"
    "💵 Выплачено всего: <b>61\u00a0000\u00a0$</b>\n"
    "\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0за 2026 год: 61\u00a0000\u00a0$\n"
    "\n"
    "📈 Доходность сейчас: 2,00% в мес. · <b>24,0% годовых</b>\n"
    "\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0без учёта сентября: 2,29% в мес. · <b>27,4% годовых</b>\n"
    "🎯 Целевая: 1,78% в мес. · <b>21,4% годовых</b>\n"
    "✅ Опережение: +0,22\u00a0п.п. в мес. · <b>+2,6\u00a0п.п. годовых</b>\n"
    "\n"
    "📅 <b>По плану на сегодня</b> (февраль–сентябрь):\n"
    "Должно быть выплачено: 49\u00a0933\u00a0$\n"
    "Выплачено: 56\u00a0000\u00a0$\n"
    "🟢 Сверх плана: <b>6\u00a0067\u00a0$</b>\n"
    "\n"
    "🧾 <b>Последние выплаты:</b>\n"
    "21.10 — 5\u00a0000\u00a0$ · тело инвестиций за октябрь\n"
    "03.09 — 8\u00a0000\u00a0$ · доля прибыли за август\n"
    "03.08 — 8\u00a0000\u00a0$ · доля прибыли за июль"
)

# n8n invReportAllTnt1, lemonaqua, today=2026-10-26
A2 = (
    "📊 <b>Lemonfit AQUA</b> · 26.10.2026\n"
    "\n"
    "💰 Вложено всего: <b>399\u00a0585\u00a0$</b> (+20\u00a0000\u00a0$ на согласовании)\n"
    "💵 Выплачено всего: <b>85\u00a0001\u00a0$</b> (+3\u00a0000\u00a0$ на согласовании)\n"
    "\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0за 2026 год: 76\u00a0001\u00a0$\n"
    "\n"
    "📈 Доходность сейчас: 2,38% в мес. · <b>28,5% годовых</b>\n"
    "🎯 Целевая: 2,89% в мес. · <b>34,7% годовых</b>\n"
    "⚠️ Отставание: −0,52\u00a0п.п. в мес. · <b>−6,2\u00a0п.п. годовых</b>\n"
    "\n"
    "📅 <b>По плану на сегодня</b> (февраль–сентябрь):\n"
    "Должно быть выплачено: 92\u00a0491\u00a0$\n"
    "Выплачено: 76\u00a0001\u00a0$\n"
    "🔻 Дефицит: <b>16\u00a0490\u00a0$</b> (+3\u00a0000\u00a0$ на согласовании)\n"
    "\n"
    "🧾 <b>Последние выплаты:</b>\n"
    "08.09 — 11\u00a0500\u00a0$ · доля прибыли за август\n"
    "06.08 — 10\u00a0000\u00a0$ · тело инвестиций за июль\n"
    "07.07 — 12\u00a0000\u00a0$ · доля прибыли за июнь"
)

# n8n invReportAllTnt1, lemonfit, today=2026-10-26
O2 = (
    "📊 <b>Lemonfit ONE</b> · 26.10.2026\n"
    "\n"
    "💰 Вложено всего: <b>350\u00a0000\u00a0$</b> (+500\u00a0000\u00a0$ на согласовании)\n"
    "💵 Выплачено всего: <b>61\u00a0000\u00a0$</b>\n"
    "\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0за 2026 год: 61\u00a0000\u00a0$\n"
    "\n"
    "📈 Доходность сейчас: 2,00% в мес. · <b>24,0% годовых</b>\n"
    "🎯 Целевая: 1,78% в мес. · <b>21,4% годовых</b>\n"
    "✅ Опережение: +0,22\u00a0п.п. в мес. · <b>+2,6\u00a0п.п. годовых</b>\n"
    "\n"
    "📅 <b>По плану на сегодня</b> (февраль–сентябрь):\n"
    "Должно быть выплачено: 49\u00a0933\u00a0$\n"
    "Выплачено: 56\u00a0000\u00a0$\n"
    "🟢 Сверх плана: <b>6\u00a0067\u00a0$</b>\n"
    "\n"
    "🧾 <b>Последние выплаты:</b>\n"
    "21.10 — 5\u00a0000\u00a0$ · тело инвестиций за октябрь\n"
    "03.09 — 8\u00a0000\u00a0$ · доля прибыли за август\n"
    "03.08 — 8\u00a0000\u00a0$ · доля прибыли за июль"
)

# n8n invReportAllTnt1, lemonhavo, today=2026-10-26
H2 = (
    "📊 <b>Lemon HAVO</b> · 26.10.2026\n"
    "\n"
    "💰 Вложено всего: <b>250\u00a0000\u00a0$</b>\n"
    "💵 Выплачено всего: <b>0\u00a0$</b>\n"
    "\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0за 2026 год: 0\u00a0$\n"
    "\n"
    "📈 Доходность сейчас: 0,00% в мес. · <b>0,0% годовых</b>"
)

# n8n invReportAllTnt1, lemonaqua, today=2026-01-20
A_JAN = (
    "📊 <b>Lemonfit AQUA</b> · 20.01.2026\n"
    "\n"
    "💰 Вложено всего: <b>399\u00a0585\u00a0$</b> (+20\u00a0000\u00a0$ на согласовании)\n"
    "💵 Выплачено всего: <b>85\u00a0001\u00a0$</b> (+3\u00a0000\u00a0$ на согласовании)\n"
    "\u00a0\u00a0\u00a0\u00a0\u00a0\u00a0за 2026 год: 76\u00a0001\u00a0$\n"
    "\n"
    "📈 Доходность: в 2026 году ещё нет завершённых месяцев для расчёта\n"
    "\n"
    "🧾 <b>Последние выплаты:</b>\n"
    "08.09 — 11\u00a0500\u00a0$ · доля прибыли за август\n"
    "06.08 — 10\u00a0000\u00a0$ · тело инвестиций за июль\n"
    "07.07 — 12\u00a0000\u00a0$ · доля прибыли за июнь"
)


def d(value: str) -> date:
    return date.fromisoformat(value)


def tashkent(y, m, day, h, mi=0):
    return dt.datetime(y, m, day, h, mi, tzinfo=TZ)


class InvestorReportFixtures:
    """Mixin: self.make_fixtures() creates the three reference tenants, rates and an admin."""

    def make_fixtures(self):
        User.objects.update_or_create(pk=1, defaults={"username": "system"})
        self.admin = User.objects.create_user(
            username="ir-admin", password="x", full_name="Админ Отчёта", telegram_chat_id=92000, telegram_from_id=92000
        )
        for rate_date, rate in RATES:
            CbuExchangeRate.objects.create(date=d(rate_date), usd_uzs_rate=Decimal(rate))
        self.tenants = {}
        for subdomain, data in TENANT_DATA.items():
            tenant = Tenant.objects.create(name=data["name"], subdomain=subdomain, is_active=True)
            TenantModuleConfig.objects.create(tenant=tenant, module_key="investments", is_enabled=True)
            TenantMembership.objects.create(tenant=tenant, user=self.admin, is_active=True)
            TenantUserRole.objects.create(tenant=tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
            for inv_date, amount, currency, confirmed in data["investments"]:
                ProjectInvestment.objects.create(
                    tenant=tenant, date=d(inv_date), amount=Decimal(amount), currency=currency,
                    confirmed=confirmed, created_by=self.admin,
                )
            for ret_date, billing, amount, currency, confirmed, kind, recipient in data["returns"]:
                InvestReturn.objects.create(
                    tenant=tenant, date=d(ret_date), billing_date=d(billing), sum=Decimal(amount), currency=currency,
                    confirmed=confirmed, type=kind, recipient=recipient, created_by=self.admin,
                )
            chat = TenantTelegramChat.objects.create(
                tenant=tenant, name=f"Инвесторы {subdomain}", chat_id=f"-100{len(self.tenants) + 1}", created_by=self.admin
            )
            InvestReportConfig.objects.create(
                tenant=tenant,
                telegram_chat=chat,
                target_annual_rate=data["target"],
                start_month=data["start_month"],
            )
            self.tenants[subdomain] = tenant

    def text_for(self, subdomain: str, today: date, **overrides) -> str:
        tenant = self.tenants[subdomain]
        config = InvestReportConfig.objects.get(tenant=tenant)
        for key, value in overrides.items():
            setattr(config, key, value)
        report = build_investor_report(tenant=tenant, today=today, config=config)
        return format_investor_report(report, tenant_name=tenant.name)


class ReferenceTextTests(InvestorReportFixtures, TestCase):
    """Texts must match the n8n draft character for character."""

    def setUp(self):
        self.make_fixtures()

    def test_aqua_on_23_october_with_line_without_september(self):
        self.assertEqual(self.text_for("lemonaqua", date(2026, 10, 23)), A1)

    def test_aqua_on_26_october_without_that_line(self):
        self.assertEqual(self.text_for("lemonaqua", date(2026, 10, 26)), A2)

    def test_one_on_23_october(self):
        self.assertEqual(self.text_for("lemonfit", date(2026, 10, 23)), O1)

    def test_one_on_26_october(self):
        self.assertEqual(self.text_for("lemonfit", date(2026, 10, 26)), O2)

    def test_havo_without_target_and_payouts(self):
        self.assertEqual(self.text_for("lemonhavo", date(2026, 10, 26)), H2)

    def test_january_has_no_finished_months(self):
        self.assertEqual(self.text_for("lemonaqua", date(2026, 1, 20)), A_JAN)

    def test_tenant_name_is_escaped(self):
        tenant = self.tenants["lemonhavo"]
        tenant.name = "A&B <Invest>"
        report = build_investor_report(tenant=tenant, today=date(2026, 10, 26), config=None)
        text = format_investor_report(report, tenant_name=tenant.name)
        self.assertTrue(text.startswith("📊 <b>A&amp;B &lt;Invest&gt;</b> · 26.10.2026\n"), text)

    def test_last_payouts_show_year_of_previous_years(self):
        text = self.text_for("lemonaqua", date(2026, 10, 26), last_payouts_count=10)
        self.assertIn(f"10.01 — 9{NBSP}000{NBSP}$ · доля прибыли за декабрь 2025", text)
        self.assertIn(f"08.09 — 11{NBSP}500{NBSP}$ · доля прибыли за август\n", text)
        self.assertEqual(text.count(" · доля прибыли за ") + text.count(" · тело инвестиций за "), 8)

    def test_partner_payouts_are_ignored(self):
        report = build_investor_report(
            tenant=self.tenants["lemonaqua"], today=date(2026, 10, 26), config=ReportSettings(last_payouts_count=10)
        )
        self.assertNotIn(Decimal("4000.00"), [p.usd for p in report.last_payouts])
        self.assertEqual(len(report.last_payouts), 8)

    def test_uzs_rows_use_rate_on_or_before_their_date(self):
        report = build_investor_report(tenant=self.tenants["lemonhavo"], today=date(2026, 10, 26), config=None)
        # 1 265 025 000 UZS on Monday 15.06 → nearest previous rate 12 650,25 (08.05) = 100 000 USD.
        self.assertEqual(report.invested, Decimal("250000"))

    def test_no_rates_at_all_raises(self):
        CbuExchangeRate.objects.all().delete()
        with self.assertRaises(InvestorReportError):
            build_investor_report(tenant=self.tenants["lemonhavo"], today=date(2026, 10, 26), config=None)


class RateOnOrBeforeTests(TestCase):
    def setUp(self):
        CbuExchangeRate.objects.create(date=date(2026, 5, 8), usd_uzs_rate=Decimal("12650.250000"))  # Friday
        CbuExchangeRate.objects.create(date=date(2026, 5, 11), usd_uzs_rate=Decimal("12700.000000"))

    def _both(self, day):
        return usd_uzs_rate_on_or_before(day), usd_uzs_rate_on_or_before(day, cache={})

    def test_exact_date(self):
        self.assertEqual(self._both(date(2026, 5, 11)), (Decimal("12700.000000"),) * 2)

    def test_weekend_takes_friday(self):
        self.assertEqual(self._both(date(2026, 5, 10)), (Decimal("12650.250000"),) * 2)

    def test_before_archive_takes_earliest(self):
        self.assertEqual(self._both(date(2020, 1, 1)), (Decimal("12650.250000"),) * 2)

    def test_empty_archive(self):
        CbuExchangeRate.objects.all().delete()
        self.assertEqual(self._both(date(2026, 5, 10)), (None, None))

    @patch("apps.modules.investments.services.fetch_cbu_usd_uzs_rate")
    def test_never_hits_network_and_cache_reads_archive_once(self, fetch):
        cache = {}
        with self.assertNumQueries(1):
            for day in (date(2026, 5, 9), date(2026, 5, 12), date(2026, 1, 1)):
                usd_uzs_rate_on_or_before(day, cache=cache)
        fetch.assert_not_called()


RATE_WARNING = "⚠️ Курс ЦБ может быть неактуален: нет связи с источником"


class PreliminaryRateNoteTests(InvestorReportFixtures, TestCase):
    """UZS row dated after the newest archived rate → one warning line at the end of the text."""

    def setUp(self):
        self.make_fixtures()
        self.tenant = self.tenants["lemonhavo"]

    def _uzs_investment(self, on: date):
        ProjectInvestment.objects.create(
            tenant=self.tenant, date=on, amount=Decimal("125000000.00"), currency="UZS",
            confirmed=True, created_by=self.admin,
        )

    @patch("apps.modules.investments.services.fetch_cbu_usd_uzs_rate")
    def test_note_when_rate_for_row_date_not_loaded_yet(self, fetch):
        self._uzs_investment(date(2026, 10, 20))  # newest archived rate is 01.09.2026

        report = build_investor_report(tenant=self.tenant, today=date(2026, 10, 26), config=None)
        text = format_investor_report(report, tenant_name=self.tenant.name)

        self.assertEqual(report.preliminary_rate, (date(2026, 10, 20), date(2026, 9, 1)))
        self.assertTrue(
            text.endswith(f"\n\n{RATE_WARNING} (последний курс на 01.09.2026)."), text
        )
        self.assertEqual(text.count(RATE_WARNING), 1)
        fetch.assert_not_called()

    def test_no_note_once_rate_is_loaded(self):
        self._uzs_investment(date(2026, 10, 20))
        CbuExchangeRate.objects.create(date=date(2026, 10, 20), usd_uzs_rate=Decimal("12500.00"))

        report = build_investor_report(tenant=self.tenant, today=date(2026, 10, 26), config=None)

        self.assertIsNone(report.preliminary_rate)
        self.assertNotIn(RATE_WARNING, format_investor_report(report, tenant_name=self.tenant.name))

    def test_usd_rows_after_archive_need_no_rate_and_no_note(self):
        ProjectInvestment.objects.create(
            tenant=self.tenant, date=date(2026, 10, 20), amount=Decimal("100.00"), currency="USD",
            confirmed=True, created_by=self.admin,
        )
        report = build_investor_report(tenant=self.tenant, today=date(2026, 10, 26), config=None)
        self.assertIsNone(report.preliminary_rate)


def inv(day, usd, confirmed=True):
    return ReportRow(date=d(day), usd=Decimal(usd), confirmed=confirmed)


def ret(day, billing, usd, confirmed=True, kind="доля_прибыли"):
    return ReportRow(date=d(day), billing_date=d(billing), usd=Decimal(usd), confirmed=confirmed, type=kind)


def compute(today, investments=(), returns=(), **settings):
    return compute_investor_report(
        today=today, investments=list(investments), returns=list(returns), settings=ReportSettings(**settings)
    )


class ComputeTests(SimpleTestCase):
    def test_nothing_at_all(self):
        report = compute(date(2026, 10, 26))
        self.assertEqual((report.invested, report.paid_total, report.paid_year), (0, 0, 0))
        self.assertIsNone(report.annual_rate)
        text = format_investor_report(report, tenant_name="T")
        self.assertNotIn("Доходность", text)
        self.assertNotIn("Последние выплаты", text)

    def test_only_investments(self):
        report = compute(date(2026, 10, 26), [inv("2025-01-10", "1000")])
        self.assertEqual(report.annual_rate, 0)
        self.assertEqual(report.months, 9)
        self.assertEqual(report.last_payouts, ())

    def test_only_payouts_has_no_yield_block(self):
        report = compute(date(2026, 10, 26), returns=[ret("2026-03-01", "2026-02-01", "500")])
        self.assertIsNone(report.annual_rate)
        text = format_investor_report(report, tenant_name="T")
        self.assertNotIn("📈", text)
        self.assertIn("🧾 <b>Последние выплаты:</b>", text)

    def test_unconfirmed_rows_are_only_pending(self):
        report = compute(
            date(2026, 10, 26),
            [inv("2025-01-10", "1000"), inv("2026-10-01", "700", confirmed=False)],
            [ret("2026-03-01", "2026-02-01", "100"), ret("2026-10-20", "2026-09-01", "40", confirmed=False)],
        )
        self.assertEqual((report.invested, report.invested_pending), (Decimal("1000"), Decimal("700")))
        self.assertEqual((report.paid_total, report.paid_pending), (Decimal("100"), Decimal("40")))
        self.assertEqual(len(report.last_payouts), 1)

    def test_start_month_default_after_first_investment_of_year(self):
        report = compute(date(2026, 10, 26), [inv("2025-01-10", "1000"), inv("2026-04-15", "500")])
        self.assertEqual((report.start_month, report.months), (5, 5))

    def test_start_month_default_january_without_investments_this_year(self):
        report = compute(date(2026, 10, 26), [inv("2025-01-10", "1000"), inv("2026-04-15", "500", confirmed=False)])
        self.assertEqual((report.start_month, report.months), (1, 9))

    def test_start_month_from_settings(self):
        report = compute(date(2026, 10, 26), [inv("2026-04-15", "500")], start_month=2)
        self.assertEqual((report.start_month, report.months), (2, 8))

    def _late(self, today, returns, **settings):
        return compute(today, [inv("2025-01-10", "12000")], returns, **settings)

    def test_without_last_month_until_late_payment_day(self):
        returns = [ret("2026-08-05", "2026-07-01", "300"), ret("2026-09-05", "2026-08-01", "300")]
        on_25 = self._late(date(2026, 10, 25), returns, start_month=7)
        self.assertEqual(on_25.skipped_month, 9)
        self.assertEqual(on_25.annual_rate_without_last, Decimal("30"))
        self.assertEqual(on_25.annual_rate, Decimal("20"))
        self.assertIsNone(self._late(date(2026, 10, 26), returns, start_month=7).annual_rate_without_last)
        self.assertIsNotNone(self._late(date(2026, 10, 20), returns, start_month=7, late_payment_day=20).skipped_month)
        self.assertIsNone(self._late(date(2026, 10, 21), returns, start_month=7, late_payment_day=20).skipped_month)

    def test_without_last_month_not_when_single_month(self):
        report = self._late(date(2026, 10, 20), [ret("2026-08-05", "2026-07-01", "300")], start_month=9)
        self.assertEqual(report.months, 1)
        self.assertIsNone(report.annual_rate_without_last)

    def test_without_last_month_not_when_last_month_paid(self):
        returns = [ret("2026-09-05", "2026-08-01", "300"), ret("2026-10-05", "2026-09-01", "300")]
        self.assertIsNone(self._late(date(2026, 10, 20), returns, start_month=8).annual_rate_without_last)

    def test_without_last_month_not_when_nothing_paid(self):
        self.assertIsNone(self._late(date(2026, 10, 20), [], start_month=8).annual_rate_without_last)

    def test_deficit_with_pending_in_brackets(self):
        report = compute(
            date(2026, 10, 26),
            [inv("2025-01-10", "12000")],
            [ret("2026-02-05", "2026-01-01", "100"), ret("2026-10-20", "2026-09-01", "55", confirmed=False)],
            target_annual_rate=Decimal("12"),
        )
        self.assertEqual(report.planned, Decimal("1080"))
        self.assertEqual(report.gap, Decimal("980"))
        text = format_investor_report(report, tenant_name="T")
        self.assertIn(f"🔻 Дефицит: <b>980{NBSP}$</b> (+55{NBSP}$ на согласовании)", text)
        self.assertIn(f"Должно быть выплачено: 1{NBSP}080{NBSP}$", text)
        self.assertIn("(январь–сентябрь):", text)

    def test_surplus_when_rounded_gap_not_positive(self):
        report = compute(
            date(2026, 2, 26),
            [inv("2025-01-10", "12000")],
            [ret("2026-02-05", "2026-01-01", "119.6")],
            target_annual_rate=Decimal("12"),
        )
        text = format_investor_report(report, tenant_name="T")
        self.assertIn(f"🟢 Сверх плана: <b>0{NBSP}$</b>", text)  # gap 0,4 → Math.round → 0
        self.assertIn("(январь):", text)
        self.assertNotIn("на согласовании", text)

    def test_zero_target_means_no_target(self):
        report = compute(date(2026, 10, 26), [inv("2025-01-10", "12000")], target_annual_rate=Decimal("0"))
        self.assertIsNone(report.target_annual_rate)
        self.assertNotIn("🎯", format_investor_report(report, tenant_name="T"))

    def test_last_payouts_order_and_limit(self):
        returns = [
            ret("2026-03-05", "2026-02-01", "1"),
            ret("2026-05-05", "2026-03-01", "2"),
            ret("2026-05-05", "2026-04-01", "3"),
            ret("2026-04-05", "2026-05-01", "4"),
        ]
        report = compute(date(2026, 10, 26), returns=returns, last_payouts_count=3)
        self.assertEqual([p.usd for p in report.last_payouts], [Decimal("3"), Decimal("2"), Decimal("4")])
        self.assertEqual(compute(date(2026, 10, 26), returns=returns, last_payouts_count=0).last_payouts, ())


class FormatterNumberTests(SimpleTestCase):
    def test_numbers_like_js_to_fixed(self):
        from apps.modules.investments.investor_report_formatter import _num, _pct, _pp, _usd

        self.assertEqual(_usd(Decimal("1234567.5")), f"1{NBSP}234{NBSP}568{NBSP}$")
        self.assertEqual(_usd(Decimal("0.4")), f"0{NBSP}$")
        self.assertEqual(_num(Decimal("-0.004"), 2), "0,00")
        self.assertEqual(_num(Decimal("-1.5")), "−2")  # (1.5).toFixed(0) === "2"
        self.assertEqual(_pct(Decimal("2.25")), "2,3%")  # (2.25).toFixed(1) === "2.3"
        self.assertEqual(_pp(Decimal("0.001")), f"+0,0{NBSP}п.п.")
        self.assertEqual(_pp(Decimal("-6.24")), f"−6,2{NBSP}п.п.")


@override_settings(BASE_DOMAIN="example.com")
class RunInvestReportsTests(InvestorReportFixtures, TestCase):
    MONDAY_10 = tashkent(2026, 10, 26, 10)

    def setUp(self):
        self.make_fixtures()
        InvestReportConfig.objects.update(is_active=True)
        self.aqua = self.tenants["lemonaqua"]
        # Only AQUA is due at Monday 10:00 unless a test says otherwise.
        InvestReportConfig.objects.exclude(tenant=self.aqua).update(weekday=2)

    @patch(GATEWAY_PATH)
    def test_monday_10_sends_once_to_group(self, gw):
        gw.side_effect = gateway_ok()
        self.assertEqual(process_due_reports(now_dt=self.MONDAY_10), 1)
        gw.assert_called_once()
        payload = gw.call_args.kwargs["payload"]
        self.assertEqual(payload["recipient_id"], "-1001")
        self.assertEqual(payload["text"], A2)
        dispatch = InvestReportDispatch.objects.get()
        self.assertEqual(
            (dispatch.tenant, dispatch.report_date, dispatch.kind, dispatch.status, dispatch.chat_id),
            (self.aqua, date(2026, 10, 26), "scheduled", "sent", "-1001"),
        )
        self.assertEqual(dispatch.text, A2)
        self.assertEqual(dispatch.telegram_message, TelegramMessage.objects.get())
        self.assertTrue(dispatch.telegram_message.history.filter(action="send", text=A2).exists())

    @patch(GATEWAY_PATH)
    def test_other_hour_or_day_is_silent(self, gw):
        gw.side_effect = gateway_ok()
        self.assertEqual(process_due_reports(now_dt=tashkent(2026, 10, 26, 9)), 0)
        self.assertEqual(process_due_reports(now_dt=tashkent(2026, 10, 27, 10)), 0)
        gw.assert_not_called()
        self.assertFalse(InvestReportDispatch.objects.exists())

    @patch(GATEWAY_PATH)
    def test_second_run_same_day_does_not_duplicate(self, gw):
        gw.side_effect = gateway_ok()
        process_due_reports(now_dt=self.MONDAY_10)
        self.assertEqual(process_due_reports(now_dt=tashkent(2026, 10, 26, 10, 30)), 0)
        self.assertEqual(gw.call_count, 1)
        self.assertEqual(InvestReportDispatch.objects.count(), 1)

    @patch(GATEWAY_PATH, return_value=None)
    def test_gateway_error_is_failed(self, gw):
        self.assertEqual(process_due_reports(now_dt=self.MONDAY_10), 0)
        dispatch = InvestReportDispatch.objects.get()
        self.assertEqual(dispatch.status, "failed")
        self.assertIsNone(dispatch.telegram_message)
        self.assertTrue(dispatch.error)
        self.assertEqual(dispatch.text, A2)

    @patch(GATEWAY_PATH)
    def test_inactive_chat_is_failed(self, gw):
        gw.side_effect = gateway_ok()
        TenantTelegramChat.objects.filter(tenant=self.aqua).update(is_active=False)
        process_due_reports(now_dt=self.MONDAY_10)
        gw.assert_not_called()
        self.assertEqual(InvestReportDispatch.objects.get().status, "failed")

    @patch(GATEWAY_PATH)
    def test_disabled_module_tenant_or_config_is_silent(self, gw):
        gw.side_effect = gateway_ok()
        TenantModuleConfig.objects.filter(tenant=self.aqua).update(is_enabled=False)
        self.assertEqual(process_due_reports(now_dt=self.MONDAY_10), 0)
        TenantModuleConfig.objects.filter(tenant=self.aqua).update(is_enabled=True)
        Tenant.objects.filter(pk=self.aqua.pk).update(is_active=False)
        self.assertEqual(process_due_reports(now_dt=self.MONDAY_10), 0)
        Tenant.objects.filter(pk=self.aqua.pk).update(is_active=True)
        InvestReportConfig.objects.filter(tenant=self.aqua).update(is_active=False)
        self.assertEqual(process_due_reports(now_dt=self.MONDAY_10), 0)
        gw.assert_not_called()
        self.assertFalse(InvestReportDispatch.objects.exists())

    @patch(GATEWAY_PATH)
    def test_one_tenant_failure_does_not_stop_others(self, gw):
        gw.side_effect = gateway_ok()
        InvestReportConfig.objects.update(weekday=0)
        real_build = build_investor_report

        def flaky(*, tenant, today, config):
            if tenant.subdomain == "lemonaqua":
                raise RuntimeError("boom")
            return real_build(tenant=tenant, today=today, config=config)

        with patch("apps.modules.investments.investor_report_jobs.build_investor_report", side_effect=flaky):
            self.assertEqual(process_due_reports(now_dt=self.MONDAY_10), 2)
        statuses = dict(InvestReportDispatch.objects.values_list("tenant__subdomain", "status"))
        self.assertEqual(statuses, {"lemonaqua": "failed", "lemonfit": "sent", "lemonhavo": "sent"})

    @patch(GATEWAY_PATH)
    def test_command_sends(self, gw):
        gw.side_effect = gateway_ok()
        out = StringIO()
        call_command("run_invest_reports", "--now=2026-10-26T10:00:00+05:00", stdout=out)
        self.assertIn("Investor reports dispatched: 1", out.getvalue())

    @patch(GATEWAY_PATH)
    def test_dry_run_prints_all_tenants_and_writes_nothing(self, gw):
        InvestReportConfig.objects.update(is_active=False)
        out = StringIO()
        call_command("run_invest_reports", "--dry-run", "--now=2026-10-26T10:00:00+05:00", stdout=out)
        gw.assert_not_called()
        self.assertFalse(InvestReportDispatch.objects.exists())
        self.assertFalse(TelegramMessage.objects.exists())
        output = out.getvalue()
        for text in (A2, O2, H2):
            self.assertIn(text, output)
        self.assertIn("===== lemonaqua chat=-1001 due=no =====", output)

    @patch(GATEWAY_PATH)
    def test_dry_run_single_tenant(self, gw):
        out = StringIO()
        call_command("run_invest_reports", "--dry-run", "--tenant=lemonfit", "--now=2026-10-23T10:00:00+05:00", stdout=out)
        self.assertIn(O1, out.getvalue())
        self.assertNotIn("Lemonfit AQUA", out.getvalue())


class CrontabTests(SimpleTestCase):
    def test_hourly_cron_entry(self):
        crontab = (Path(django_settings.BASE_DIR) / "cron" / "crontab").read_text()
        self.assertIn("0 * * * * root cd /app && python manage.py run_invest_reports >> /proc/1/fd/1 2>&1", crontab)


class MigrationsInSyncTests(TestCase):
    def test_no_missing_migrations_for_investments(self):
        out = StringIO()
        try:
            call_command("makemigrations", "investments", "--check", "--dry-run", stdout=out, stderr=out)
        except SystemExit:
            self.fail(f"investments models and migrations are out of sync:\n{out.getvalue()}")


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class InvestReportApiTests(InvestorReportFixtures, APITestCase):
    host = "lemonaqua.example.com"
    BASE = "/api/investments/report/"

    def setUp(self):
        self.make_fixtures()
        self.aqua = self.tenants["lemonaqua"]
        self.chat = TenantTelegramChat.objects.get(tenant=self.aqua)
        self.investor = User.objects.create_user(username="ir-investor", password="x")
        TenantMembership.objects.create(tenant=self.aqua, user=self.investor, is_active=True)
        TenantUserRole.objects.create(tenant=self.aqua, user=self.investor, role=TenantUserRole.ROLE_INVESTOR)
        self.client.force_authenticate(self.admin)

    def _payload(self, **overrides):
        data = {
            "is_active": True,
            "telegram_chat_id": self.chat.id,
            "weekday": 0,
            "send_hour": 10,
            "target_annual_rate": "34.72",
            "start_month": None,
            "last_payouts_count": 3,
            "late_payment_day": 25,
        }
        data.update(overrides)
        return data

    def get(self, path, **params):
        return self.client.get(self.BASE + path, params, HTTP_HOST=self.host)

    def post(self, path, data=None):
        return self.client.post(self.BASE + path, data or {}, format="json", HTTP_HOST=self.host)

    def put_config(self, **overrides):
        return self.client.put(self.BASE + "config/", self._payload(**overrides), format="json", HTTP_HOST=self.host)

    def test_get_config_with_chat_options(self):
        res = self.get("config/")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["telegram_chat_id"], self.chat.id)
        self.assertEqual(res.data["target_annual_rate"], "34.72")
        self.assertEqual(res.data["options"]["chats"], [{"id": self.chat.id, "name": self.chat.name}])

    def test_get_config_defaults_without_saved_config(self):
        InvestReportConfig.objects.filter(tenant=self.aqua).delete()
        res = self.get("config/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            {k: res.data[k] for k in ("is_active", "weekday", "send_hour", "last_payouts_count", "late_payment_day")},
            {"is_active": False, "weekday": 0, "send_hour": 10, "last_payouts_count": 3, "late_payment_day": 25},
        )

    def test_put_config_saves(self):
        res = self.put_config(send_hour=11, start_month=2, target_annual_rate="21.4")
        self.assertEqual(res.status_code, 200, res.content)
        config = InvestReportConfig.objects.get(tenant=self.aqua)
        self.assertEqual((config.is_active, config.send_hour, config.start_month), (True, 11, 2))
        self.assertEqual(config.target_annual_rate, Decimal("21.40"))
        self.assertEqual(config.updated_by, self.admin)

    def test_put_rejects_foreign_or_inactive_chat(self):
        foreign = TenantTelegramChat.objects.get(tenant=self.tenants["lemonfit"])
        self.assertEqual(self.put_config(telegram_chat_id=foreign.id).status_code, 400)
        TenantTelegramChat.objects.filter(pk=self.chat.pk).update(is_active=False)
        self.assertEqual(self.put_config().status_code, 400)

    def test_put_rejects_enabling_without_chat(self):
        res = self.put_config(telegram_chat_id=None)
        self.assertEqual(res.status_code, 400)
        self.assertIn("telegram_chat_id", res.data)
        self.assertEqual(self.put_config(telegram_chat_id=None, is_active=False).status_code, 200)

    def test_put_validates_ranges(self):
        for field, value in (
            ("weekday", 7), ("send_hour", 24), ("start_month", 13), ("start_month", 0),
            ("target_annual_rate", "1000.01"), ("target_annual_rate", "-1"),
            ("last_payouts_count", 11), ("late_payment_day", 0), ("late_payment_day", 32),
        ):
            with self.subTest(field=field, value=value):
                res = self.put_config(**{field: value})
                self.assertEqual(res.status_code, 400)
                self.assertIn(field, res.data)

    def test_module_user_cannot_manage_config_or_send_now(self):
        self.client.force_authenticate(self.investor)
        self.assertEqual(self.get("config/").status_code, 403)
        self.assertEqual(self.put_config().status_code, 403)
        self.assertEqual(self.post("send-now/").status_code, 403)
        self.assertEqual(self.get("dispatches/").status_code, 403)
        self.assertEqual(self.get("preview/").status_code, 200)

    def test_director_without_module_role_can_configure(self):
        director = User.objects.create_user(username="ir-director", password="x")
        TenantMembership.objects.create(tenant=self.aqua, user=director, is_active=True)
        TenantUserRole.objects.create(tenant=self.aqua, user=director, role=TenantUserRole.ROLE_DIRECTOR)
        self.client.force_authenticate(director)
        self.assertEqual(self.get("config/").status_code, 200)
        self.assertEqual(self.get("preview/").status_code, 200)

    def test_disabled_module_is_forbidden(self):
        TenantModuleConfig.objects.filter(tenant=self.aqua).update(is_enabled=False)
        self.assertEqual(self.get("config/").status_code, 403)
        self.assertEqual(self.get("preview/").status_code, 403)

    def test_preview_returns_text_and_metrics(self):
        res = self.get("preview/", date="2026-10-23")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["text"], A1)
        self.assertEqual(res.data["metrics"]["months"], 8)
        self.assertEqual(res.data["metrics"]["skipped_month"], 9)

    def test_preview_query_overrides_saved_settings(self):
        res = self.get("preview/", date="2026-10-26", target_annual_rate="", last_payouts_count=1, start_month=3)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertNotIn("🎯", res.data["text"])
        self.assertEqual(res.data["metrics"]["start_month"], 3)
        self.assertEqual(len(res.data["metrics"]["last_payouts"]), 1)
        self.assertEqual(InvestReportConfig.objects.get(tenant=self.aqua).target_annual_rate, Decimal("34.72"))

    def test_preview_rejects_future_date_and_bad_values(self):
        self.assertEqual(self.get("preview/", date="2999-01-01").status_code, 400)
        self.assertEqual(self.get("preview/", start_month=13).status_code, 400)

    @patch(GATEWAY_PATH)
    def test_send_test_without_telegram(self, gw):
        self.client.force_authenticate(self.investor)
        res = self.post("send-test/")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["detail"], "Привяжите Telegram в профиле")
        gw.assert_not_called()

    @patch(GATEWAY_PATH)
    def test_send_test_goes_to_own_chat(self, gw):
        gw.side_effect = gateway_ok()
        res = self.post("send-test/", {"date": "2026-10-23"})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["status"], "sent")
        payload = gw.call_args.kwargs["payload"]
        self.assertEqual((payload["recipient_id"], payload["text"]), ("92000", A1))
        dispatch = InvestReportDispatch.objects.get()
        self.assertEqual((dispatch.kind, dispatch.created_by), ("test", self.admin))

    @patch(GATEWAY_PATH)
    def test_send_now_to_group_and_journal(self, gw):
        gw.side_effect = gateway_ok()
        res = self.post("send-now/")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.data["kind"], res.data["status"], res.data["chat_name"]), ("manual", "sent", self.chat.name))
        self.assertEqual(gw.call_args.kwargs["payload"]["recipient_id"], self.chat.chat_id)
        listing = self.get("dispatches/", limit=5)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual([row["kind"] for row in listing.data], ["manual"])

    @patch(GATEWAY_PATH)
    def test_send_now_without_active_chat(self, gw):
        InvestReportConfig.objects.filter(tenant=self.aqua).update(telegram_chat=None)
        self.assertEqual(self.post("send-now/").status_code, 400)
        gw.assert_not_called()

    @patch(GATEWAY_PATH)
    def test_manual_send_does_not_block_scheduled(self, gw):
        gw.side_effect = gateway_ok()
        InvestReportConfig.objects.update(is_active=True, weekday=2)
        InvestReportConfig.objects.filter(tenant=self.aqua).update(weekday=0)
        with patch("apps.modules.investments.views.tashkent_today", return_value=date(2026, 10, 26)):
            self.post("send-now/")
        self.assertEqual(process_due_reports(now_dt=tashkent(2026, 10, 26, 10)), 1)
