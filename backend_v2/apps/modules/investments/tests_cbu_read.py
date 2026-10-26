"""Чтение эквивалентов USD/UZS не зависает, когда сайт ЦБ недоступен (не больше одной попытки сети на запрос)."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from apps.modules.investments.models import CbuExchangeRate, ProjectInvestment
from apps.modules.investments.services import (
    CBU_READ_FETCH_TIMEOUT,
    CBU_READ_UNAVAILABLE_CACHE_KEY,
    CbuRateFetchError,
    usd_uzs_equivalents_for_read,
)
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()

FETCH = "apps.modules.investments.services.fetch_cbu_usd_uzs_rate"


class _CbuCooldownCacheMixin:
    """Пауза после неудачи живёт в кэше процесса — не протекает в другие тесты."""

    def setUp(self):
        super().setUp()
        cache.delete(CBU_READ_UNAVAILABLE_CACHE_KEY)
        self.addCleanup(cache.delete, CBU_READ_UNAVAILABLE_CACHE_KEY)


class UsdUzsEquivalentsForReadTests(_CbuCooldownCacheMixin, TestCase):
    @patch(FETCH, side_effect=CbuRateFetchError("offline"))
    def test_network_tried_once_per_memo_then_archive_only(self, mock_fetch):
        CbuExchangeRate.objects.create(date=date(2026, 10, 20), usd_uzs_rate=Decimal("12000"))
        memo: dict = {}

        first = usd_uzs_equivalents_for_read(
            sum_val=Decimal("100"), currency="USD", rate_date=date(2026, 10, 26), memo=memo
        )
        second = usd_uzs_equivalents_for_read(
            sum_val=Decimal("100"), currency="USD", rate_date=date(2026, 10, 25), memo=memo
        )
        archived = usd_uzs_equivalents_for_read(
            sum_val=Decimal("100"), currency="USD", rate_date=date(2026, 10, 20), memo=memo
        )

        self.assertEqual(first, (None, None))
        self.assertEqual(second, (None, None))
        self.assertEqual(archived, (Decimal("100.00"), Decimal("1200000.00")))
        mock_fetch.assert_called_once_with(rate_date=date(2026, 10, 26), timeout=CBU_READ_FETCH_TIMEOUT)

    @patch(FETCH, side_effect=CbuRateFetchError("offline"))
    def test_failure_pauses_network_for_next_requests(self, mock_fetch):
        first = usd_uzs_equivalents_for_read(
            sum_val=Decimal("100"), currency="USD", rate_date=date(2026, 10, 26), memo={}
        )
        # Следующий запрос портала (новый memo) в паузе сеть не трогает.
        second = usd_uzs_equivalents_for_read(
            sum_val=Decimal("100"), currency="USD", rate_date=date(2026, 10, 26), memo={}
        )

        self.assertEqual(first, (None, None))
        self.assertEqual(second, (None, None))
        self.assertEqual(mock_fetch.call_count, 1)

        cache.delete(CBU_READ_UNAVAILABLE_CACHE_KEY)
        usd_uzs_equivalents_for_read(
            sum_val=Decimal("100"), currency="USD", rate_date=date(2026, 10, 26), memo={}
        )
        self.assertEqual(mock_fetch.call_count, 2)

    @patch(FETCH, return_value=Decimal("12600"))
    def test_fetched_rate_is_archived_and_used(self, mock_fetch):
        memo: dict = {}

        out = usd_uzs_equivalents_for_read(
            sum_val=Decimal("1260000"), currency="UZS", rate_date=date(2026, 10, 26), memo=memo
        )

        self.assertEqual(out, (Decimal("100.00"), Decimal("1260000.00")))
        self.assertEqual(CbuExchangeRate.objects.get(date=date(2026, 10, 26)).usd_uzs_rate, Decimal("12600"))
        self.assertEqual(memo, {})


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class ProjectInvestmentListCbuDownTests(_CbuCooldownCacheMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = Tenant.objects.create(name="CbuDownCo", subdomain="cbudown", is_active=True)
        self.host = "cbudown.example.com"
        self.admin = User.objects.create_user(username="cbu_down_admin", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="investments", is_enabled=True)
        self.client.force_authenticate(self.admin)

    @patch(FETCH, side_effect=CbuRateFetchError("offline"))
    def test_list_tries_network_once_when_cbu_unavailable(self, mock_fetch):
        for day in (24, 25, 26):
            for _ in range(2):
                ProjectInvestment.objects.create(
                    tenant=self.tenant,
                    date=date(2026, 10, day),
                    amount=Decimal("100"),
                    currency="USD",
                    created_by=self.admin,
                )

        res = self.client.get("/api/investments/project-investments/?page_size=200", HTTP_HOST=self.host)

        self.assertEqual(res.status_code, 200, res.content)
        rows = res.data["results"] if isinstance(res.data, dict) else res.data
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(row["sum_usd"] is None for row in rows))
        self.assertEqual(mock_fetch.call_count, 1)

        # Повторное открытие списка в паузе — без похода в сеть.
        res = self.client.get("/api/investments/project-investments/?page_size=200", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(mock_fetch.call_count, 1)
