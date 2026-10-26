"""Чтение эквивалентов USD/UZS — только из архива курсов: без сети и без пропуска строк, когда ЦБ недоступен."""

from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from apps.modules.investments.models import CbuExchangeRate, ProjectInvestment
from apps.modules.investments.services import CbuRateFetchError, usd_uzs_equivalents_for_read
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()

FETCH = "apps.modules.investments.services.fetch_cbu_usd_uzs_rate"
SYNC_FETCH = "apps.modules.investments.management.commands.sync_cbu_exchange_rate.fetch_cbu_usd_uzs_rate"
SYNC_TODAY = "apps.modules.investments.management.commands.sync_cbu_exchange_rate.tashkent_today"


class UsdUzsEquivalentsForReadTests(TestCase):
    @patch(FETCH)
    def test_exact_archived_rate(self, mock_fetch):
        CbuExchangeRate.objects.create(date=date(2026, 10, 20), usd_uzs_rate=Decimal("12000"))

        out = usd_uzs_equivalents_for_read(
            sum_val=Decimal("1200000"), currency="UZS", rate_date=date(2026, 10, 20), memo={}
        )

        self.assertEqual(out, (Decimal("100.00"), Decimal("1200000.00")))
        mock_fetch.assert_not_called()

    @patch(FETCH)
    def test_missing_date_uses_previous_archived_rate_without_network(self, mock_fetch):
        CbuExchangeRate.objects.create(date=date(2026, 10, 20), usd_uzs_rate=Decimal("12000"))
        CbuExchangeRate.objects.create(date=date(2026, 10, 22), usd_uzs_rate=Decimal("12500"))

        out = usd_uzs_equivalents_for_read(
            sum_val=Decimal("100"), currency="USD", rate_date=date(2026, 10, 26), memo={}
        )

        self.assertEqual(out, (Decimal("100.00"), Decimal("1250000.00")))
        mock_fetch.assert_not_called()

    def test_empty_archive_gives_no_equivalents(self):
        out = usd_uzs_equivalents_for_read(
            sum_val=Decimal("100"), currency="USD", rate_date=date(2026, 10, 26), memo={}
        )
        self.assertEqual(out, (None, None))


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class ProjectInvestmentListCbuDownTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="CbuDownCo", subdomain="cbudown", is_active=True)
        self.host = "cbudown.example.com"
        self.admin = User.objects.create_user(username="cbu_down_admin", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="investments", is_enabled=True)
        self.client.force_authenticate(self.admin)

    @patch(FETCH, side_effect=CbuRateFetchError("offline"))
    def test_list_never_hits_network_and_counts_rows_without_exact_rate(self, mock_fetch):
        CbuExchangeRate.objects.create(date=date(2026, 10, 22), usd_uzs_rate=Decimal("12000"))
        for day in (24, 25, 26):
            ProjectInvestment.objects.create(
                tenant=self.tenant,
                date=date(2026, 10, day),
                amount=Decimal("57200000"),
                currency="UZS",
                confirmed=True,
                created_by=self.admin,
            )

        res = self.client.get("/api/investments/project-investments/?page_size=200", HTTP_HOST=self.host)

        self.assertEqual(res.status_code, 200, res.content)
        rows = res.data["results"] if isinstance(res.data, dict) else res.data
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertEqual(Decimal(str(row["sum_uzs"])), Decimal("57200000.00"))
            self.assertEqual(Decimal(str(row["sum_usd"])), Decimal("4766.67"))
        mock_fetch.assert_not_called()


class SyncCbuFillGapsTests(TestCase):
    @patch(SYNC_TODAY, return_value=date(2026, 10, 27))
    @patch(SYNC_FETCH, return_value=Decimal("12100"))
    def test_fill_gaps_fetches_missing_recent_dates_only(self, mock_fetch, _today):
        CbuExchangeRate.objects.create(date=date(2026, 10, 22), usd_uzs_rate=Decimal("12000"))

        call_command("sync_cbu_exchange_rate", "--fill-gaps-days", "6", stdout=StringIO(), stderr=StringIO())

        archived = set(CbuExchangeRate.objects.values_list("date", flat=True))
        self.assertEqual(archived, {date(2026, 10, day) for day in range(21, 28)})
        fetched = [c.kwargs["rate_date"] for c in mock_fetch.call_args_list]
        # Вчера/сегодня — как раньше; пропуски 21, 23–25; уже архивное 22.10 не запрашивается.
        self.assertEqual(
            sorted(fetched),
            [date(2026, 10, 21), date(2026, 10, 23), date(2026, 10, 24), date(2026, 10, 25),
             date(2026, 10, 26), date(2026, 10, 27)],
        )
        self.assertEqual(CbuExchangeRate.objects.get(date=date(2026, 10, 22)).usd_uzs_rate, Decimal("12000"))

    @patch(SYNC_TODAY, return_value=date(2026, 10, 27))
    @patch(SYNC_FETCH, side_effect=CbuRateFetchError("offline"))
    def test_fill_gaps_stops_after_first_failure(self, mock_fetch, _today):
        call_command("sync_cbu_exchange_rate", "--fill-gaps-days", "14", stdout=StringIO(), stderr=StringIO())

        # Вчера и сегодня (как раньше) + одна попытка заполнить пропуски, дальше таймауты не ждём.
        self.assertEqual(mock_fetch.call_count, 3)
        self.assertFalse(CbuExchangeRate.objects.exists())

    @patch(SYNC_TODAY, return_value=date(2026, 10, 27))
    @patch(SYNC_FETCH, return_value=Decimal("12100"))
    def test_without_flag_only_yesterday_and_today(self, mock_fetch, _today):
        call_command("sync_cbu_exchange_rate", stdout=StringIO(), stderr=StringIO())

        self.assertEqual(
            sorted(c.kwargs["rate_date"] for c in mock_fetch.call_args_list),
            [date(2026, 10, 26), date(2026, 10, 27)],
        )
