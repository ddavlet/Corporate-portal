import datetime as dt
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.modules.corporate_card.models import CardExpense, CardExpenseAutoRequestConfig
from apps.modules.requests import card_expense_auto_requests, payment_step_guards, status_events
from apps.modules.requests.card_expense_auto_requests import (
    ACTION_CLOSED,
    ACTION_CREATED,
    ACTION_SKIPPED,
    find_auto_request_candidates,
    process_card_expense_auto_request,
    run_card_expense_auto_requests_hook,
)
from apps.modules.requests.models import (
    Approval,
    Request,
    RequestApprovalConfig,
    RequestApprovalPaymentTypeConfig,
    RequestComment,
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    RequestPaymentPurposeConfig,
)
from apps.modules.telegram_approvals.services import TelegramDispatcher
from apps.modules.vendors.models import Vendor
from apps.modules.wallets.models import CorporateCardAccount, Wallet
from apps.modules.wallets.resolution import get_or_create_corporate_wallet
from apps.tenants.models import Tenant, TenantModuleConfig

User = get_user_model()

TASHKENT = dt.timezone(dt.timedelta(hours=5))
PURPOSE = "Реклама"


def enable_card_auto_requests_for(tenant, *, updated_by):
    """Switch on the corporate_card module and an active card purpose PURPOSE for `tenant`."""
    TenantModuleConfig.objects.create(tenant=tenant, module_key="corporate_card", is_enabled=True)
    form_cfg = RequestFormConfig.objects.create(tenant=tenant, updated_by=updated_by)
    form_pt = RequestFormPaymentTypeConfig.objects.create(
        config=form_cfg, payment_type=Request.PAYMENT_TYPE_CARD, default_company_payer="ООО Лимон"
    )
    return RequestPaymentPurposeConfig.objects.create(
        payment_type_config=form_pt, name=PURPOSE, category="Маркетинг", is_active=True
    )


class CardExpenseAutoRequestTestMixin:
    """Tenant with an enabled auto-request config on its UZS corporate card."""

    def setUp(self):
        super().setUp()
        self.system = User.objects.create_user(id=1, username="app", full_name="Система", password="x")
        self.tenant = Tenant.objects.create(name="Lemon", subdomain="cardauto", is_active=True)
        self.wallet = get_or_create_corporate_wallet(tenant=self.tenant, currency="UZS")
        self.purpose_config = enable_card_auto_requests_for(self.tenant, updated_by=self.system)
        self.vendor = Vendor.objects.create(
            tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name="Meta Ads", inn="123456789", created_by=self.system
        )
        self.config = CardExpenseAutoRequestConfig.objects.create(
            tenant=self.tenant,
            wallet=self.wallet,
            is_enabled=True,
            payment_purpose=PURPOSE,
            category="Реклама онлайн",
            company_payer="ООО Лимонфит",
            vendor_ref=self.vendor,
            match_text="",
        )

        self.payed_calls = []
        self._saved_payed = status_events.REQUEST_PAYED_EVENT_HANDLERS
        self._saved_suppressors = payment_step_guards.PAYMENT_STEP_SUPPRESSORS
        status_events.REQUEST_PAYED_EVENT_HANDLERS = (self._count_payed,)
        payment_step_guards.PAYMENT_STEP_SUPPRESSORS = ()
        for name in ("send", "edit", "deactivate"):
            patcher = patch.object(TelegramDispatcher, name, return_value=None)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        status_events.REQUEST_PAYED_EVENT_HANDLERS = self._saved_payed
        payment_step_guards.PAYMENT_STEP_SUPPRESSORS = self._saved_suppressors
        super().tearDown()

    def _count_payed(self, *, request_obj):
        self.payed_calls.append(request_obj.pk)

    def _expense(
        self,
        *,
        amount="150000.00",
        currency="UZS",
        at=None,
        note="Оплата рекламы",
        title="META *ADS",
        external_id="",
        wallet=None,
        tenant=None,
        payload=None,
    ):
        return CardExpense.objects.create(
            tenant=tenant or self.tenant,
            wallet=wallet or self.wallet,
            external_id=external_id,
            title=title,
            amount=Decimal(amount),
            currency=currency,
            expense_at=at or dt.datetime(2026, 11, 10, 10, 0, tzinfo=TASHKENT),
            note=note,
            payload=payload or {},
            created_by=self.system,
        )

    def _approved_request(self, *, amount="150000.00", created_at=None):
        return Request.objects.create(
            tenant=self.tenant,
            created_by=self.system,
            requester=self.system,
            title="t",
            amount=Decimal(amount),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CARD,
            payment_purpose=PURPOSE,
            status=Request.STATUS_APPROVED,
            billing_date=dt.date(2026, 11, 1),
            created_at=created_at or dt.datetime(2026, 11, 5, 12, 0, tzinfo=TASHKENT),
        )

    def _second_card_wallet(self, tenant=None):
        tenant = tenant or self.tenant
        account = CorporateCardAccount.objects.create(tenant=tenant, currency="UZS", label="Вторая карта")
        return Wallet.objects.create(
            tenant=tenant, wallet_type=Wallet.Type.CORPORATE_CARD, currency="UZS", corporate_card_account=account
        )

    def _card_requests(self, tenant=None):
        return Request.all_objects.filter(tenant=tenant or self.tenant, payment_type=Request.PAYMENT_TYPE_CARD)


class CardExpenseAutoRequestServiceTests(CardExpenseAutoRequestTestMixin, TestCase):
    def test_created_request_fields(self):
        expense = self._expense(external_id="EXT-1")

        result = process_card_expense_auto_request(expense.pk)

        self.assertEqual(result.action, ACTION_CREATED)
        req = Request.objects.get(pk=result.request_id)
        self.assertEqual(req.tenant_id, self.tenant.pk)
        self.assertEqual(req.status, Request.STATUS_PAYED)
        self.assertEqual(req.payment_type, Request.PAYMENT_TYPE_CARD)
        self.assertEqual(req.amount, Decimal("150000.00"))
        self.assertEqual(req.currency, "UZS")
        self.assertEqual(req.payment_purpose, PURPOSE)
        self.assertEqual(req.category, "Реклама онлайн")
        self.assertEqual(req.company_payer, "ООО Лимонфит")
        self.assertEqual(req.vendor_ref_id, self.vendor.pk)
        self.assertEqual(req.vendor, "Meta Ads")
        self.assertEqual(req.created_by_id, self.system.pk)
        self.assertEqual(req.requester_id, self.system.pk)
        self.assertEqual(req.expense_ref_id, expense.pk)
        self.assertEqual(req.expense_ref_target, Request.EXPENSE_REF_TARGET_CARD)
        self.assertEqual(req.expense_id, str(expense.pk))
        self.assertEqual(self.payed_calls, [])

    def test_dates_are_tashkent_local_and_single_system_comment(self):
        # 23:30 UTC on Oct 31 is already Nov 1 in Tashkent.
        expense = self._expense(at=dt.datetime(2026, 10, 31, 23, 30, tzinfo=dt.timezone.utc))

        req = Request.objects.get(pk=process_card_expense_auto_request(expense.pk).request_id)

        self.assertEqual(req.payed_at, 20261101)
        self.assertEqual(req.billing_date, dt.date(2026, 11, 1))
        self.assertEqual((req.expense_year, req.expense_month, req.expense_day), (2026, 11, 1))
        self.assertEqual(req.created_at, expense.expense_at)
        self.assertEqual(req.description, "Оплата рекламы")
        comments = RequestComment.objects.filter(request=req)
        self.assertEqual(comments.count(), 1)
        comment = comments.get()
        self.assertEqual(comment.created_by_id, self.system.pk)
        self.assertEqual(
            comment.body,
            f"Заявка создана автоматически по расходу корпоративной карты {expense.pk} от 01.11.2026 "
            "на 150 000.00 UZS по настройке автозаявок карты.",
        )
        self.assertFalse(Approval.objects.filter(request=req).exists())

    def test_billing_date_is_first_of_month_and_description_falls_back_to_title(self):
        expense = self._expense(at=dt.datetime(2026, 11, 17, 10, 0, tzinfo=TASHKENT), note="")

        req = Request.objects.get(pk=process_card_expense_auto_request(expense.pk).request_id)

        self.assertEqual(req.billing_date, dt.date(2026, 11, 1))
        self.assertEqual(req.description, "META *ADS")

    def test_second_call_does_not_create_duplicate(self):
        expense = self._expense()

        self.assertEqual(process_card_expense_auto_request(expense.pk).action, ACTION_CREATED)
        again = process_card_expense_auto_request(expense.pk)

        self.assertEqual(again.action, ACTION_SKIPPED)
        self.assertEqual(self._card_requests().count(), 1)

    def test_expense_linked_by_expense_ref_is_skipped(self):
        expense = self._expense()
        Request.objects.create(
            tenant=self.tenant, created_by=self.system, requester=self.system, title="t", amount=1,
            payment_type=Request.PAYMENT_TYPE_CARD, status=Request.STATUS_PAYED, billing_date=dt.date(2026, 11, 1),
            expense_ref_id=expense.pk, expense_ref_target=Request.EXPENSE_REF_TARGET_CARD,
        )

        self.assertEqual(process_card_expense_auto_request(expense.pk).action, ACTION_SKIPPED)
        self.assertEqual(self._card_requests().count(), 1)

    def test_expense_linked_by_external_id_is_skipped(self):
        expense = self._expense(external_id="EXT-42")
        Request.objects.create(
            tenant=self.tenant, created_by=self.system, requester=self.system, title="t", amount=1,
            payment_type=Request.PAYMENT_TYPE_CARD, status=Request.STATUS_PAYED, billing_date=dt.date(2026, 11, 1),
            expense_id="EXT-42",
        )

        self.assertEqual(process_card_expense_auto_request(expense.pk).action, ACTION_SKIPPED)
        self.assertEqual(self._card_requests().count(), 1)

    def test_expense_linked_to_deleted_request_is_skipped(self):
        expense = self._expense()
        Request.objects.create(
            tenant=self.tenant, created_by=self.system, requester=self.system, title="t", amount=1,
            payment_type=Request.PAYMENT_TYPE_CARD, status=Request.STATUS_DELETED, billing_date=dt.date(2026, 11, 1),
            expense_ref_id=expense.pk, expense_ref_target=Request.EXPENSE_REF_TARGET_CARD,
        )

        result = process_card_expense_auto_request(expense.pk)

        self.assertEqual(result.action, ACTION_SKIPPED)
        self.assertEqual(result.reason, "расход уже связан с заявкой")
        self.assertEqual(self._card_requests().count(), 1)

    def test_match_text_is_case_insensitive_substring(self):
        self.config.match_text = "  РЕКЛАМ "
        self.config.save(update_fields=["match_text"])
        matching = self._expense(note="оплата рекламы")
        by_title = self._expense(note="", title="Реклама в META")
        other = self._expense(note="Такси", title="Yandex Go")

        self.assertEqual(process_card_expense_auto_request(matching.pk).action, ACTION_CREATED)
        self.assertEqual(process_card_expense_auto_request(by_title.pk).action, ACTION_CREATED)
        self.assertEqual(process_card_expense_auto_request(other.pk).action, ACTION_SKIPPED)
        self.assertFalse(self._card_requests().filter(expense_ref_id=other.pk).exists())

    def test_empty_match_text_matches_everything(self):
        expense = self._expense(note="", title="")
        self.assertEqual(process_card_expense_auto_request(expense.pk).action, ACTION_CREATED)

    def test_disabled_or_missing_config_creates_nothing(self):
        self.config.is_enabled = False
        self.config.save(update_fields=["is_enabled"])
        disabled = self._expense()
        no_config = self._expense(wallet=self._second_card_wallet())

        self.assertEqual(process_card_expense_auto_request(disabled.pk).action, ACTION_SKIPPED)
        self.assertEqual(process_card_expense_auto_request(no_config.pk).action, ACTION_SKIPPED)
        self.assertEqual(self._card_requests().count(), 0)

    def test_other_wallet_and_other_tenant_are_not_touched_by_hook(self):
        other_wallet_expense = self._expense(wallet=self._second_card_wallet())
        other_tenant = Tenant.objects.create(name="Other", subdomain="cardautoother", is_active=True)
        other_tenant_expense = self._expense(
            tenant=other_tenant, wallet=get_or_create_corporate_wallet(tenant=other_tenant, currency="UZS")
        )
        own = self._expense()

        done = run_card_expense_auto_requests_hook(
            tenant=self.tenant, expense_ids=[other_wallet_expense.pk, other_tenant_expense.pk, own.pk]
        )

        self.assertEqual(done, 1)
        self.assertEqual(list(self._card_requests().values_list("expense_ref_id", flat=True)), [own.pk])
        self.assertEqual(self._card_requests(tenant=other_tenant).count(), 0)

    def test_category_and_company_payer_fall_back_to_card_settings(self):
        self.config.category = ""
        self.config.company_payer = ""
        self.config.vendor_ref = None
        self.config.save(update_fields=["category", "company_payer", "vendor_ref"])
        expense = self._expense()

        req = Request.objects.get(pk=process_card_expense_auto_request(expense.pk).request_id)

        self.assertEqual(req.category, "Маркетинг")
        self.assertEqual(req.company_payer, "ООО Лимон")
        self.assertIsNone(req.vendor_ref_id)
        self.assertEqual(req.vendor, "")

    def test_hook_logs_exception_and_continues(self):
        failing = self._expense(at=dt.datetime(2026, 11, 10, 9, 0, tzinfo=TASHKENT))
        ok = self._expense(at=dt.datetime(2026, 11, 10, 11, 0, tzinfo=TASHKENT))
        real_process = card_expense_auto_requests.process_card_expense_auto_request

        def flaky(expense_id, **kwargs):
            if expense_id == failing.pk:
                raise RuntimeError("boom")
            return real_process(expense_id, **kwargs)

        with patch.object(card_expense_auto_requests, "process_card_expense_auto_request", side_effect=flaky):
            with self.assertLogs("apps.modules.requests.card_expense_auto_requests", level="ERROR") as logs:
                done = run_card_expense_auto_requests_hook(tenant=self.tenant, expense_ids=[ok.pk, failing.pk])

        self.assertEqual(done, 1)
        self.assertTrue(any(f"expense_id={failing.pk}" in line for line in logs.output))
        self.assertEqual(list(self._card_requests().values_list("expense_ref_id", flat=True)), [ok.pk])

    def test_request_not_required_rule_skips(self):
        appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant, updated_by=self.system)
        RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg,
            payment_type=Request.PAYMENT_TYPE_CARD,
            is_enabled=True,
            request_not_required_rules=[{"field": "category", "operator": "eq", "value": "ops"}],
        )
        expense = self._expense(payload={"category": "ops"})

        result = process_card_expense_auto_request(expense.pk)

        self.assertEqual(result.action, ACTION_SKIPPED)
        self.assertEqual(result.reason, "по правилам компании заявка для расхода не нужна")
        self.assertEqual(self._card_requests().count(), 0)

    def test_missing_system_user_skips(self):
        expense = self._expense()

        with patch.object(card_expense_auto_requests, "system_user", return_value=None):
            with self.assertLogs("apps.modules.requests.card_expense_auto_requests", level="WARNING"):
                result = process_card_expense_auto_request(expense.pk)

        self.assertEqual(result.action, ACTION_SKIPPED)
        self.assertEqual(self._card_requests().count(), 0)

    def test_unsupported_currency_skips(self):
        expense = self._expense(currency="KZT")

        with self.assertLogs("apps.modules.requests.card_expense_auto_requests", level="WARNING"):
            result = process_card_expense_auto_request(expense.pk)

        self.assertEqual(result.action, ACTION_SKIPPED)
        self.assertEqual(self._card_requests().count(), 0)

    def test_closes_approved_request_instead_of_creating(self):
        approved = self._approved_request()
        expense = self._expense()

        result = process_card_expense_auto_request(expense.pk)

        self.assertEqual((result.action, result.request_id), (ACTION_CLOSED, approved.pk))
        self.assertEqual(self._card_requests().count(), 1)
        approved.refresh_from_db()
        self.assertEqual(approved.status, Request.STATUS_PAYED)

    def test_long_vendor_name_is_truncated_to_request_field(self):
        self.vendor.name = "V" * 200
        self.vendor.save(update_fields=["name"])
        expense = self._expense()

        result = process_card_expense_auto_request(expense.pk)

        self.assertEqual(result.action, ACTION_CREATED)
        req = Request.objects.get(pk=result.request_id)
        self.assertEqual(req.vendor, "V" * 150)
        self.assertEqual(req.vendor_ref_id, self.vendor.pk)

    def test_disabled_corporate_card_module_creates_nothing(self):
        TenantModuleConfig.objects.filter(tenant=self.tenant, module_key="corporate_card").update(is_enabled=False)
        approved = self._approved_request()
        expense = self._expense()

        result = process_card_expense_auto_request(expense.pk)

        self.assertEqual(result.action, ACTION_SKIPPED)
        self.assertEqual(result.reason, "модуль «Корпоративные карты» у компании выключен")
        self.assertEqual(run_card_expense_auto_requests_hook(tenant=self.tenant, expense_ids=[expense.pk]), 0)
        self.assertEqual(find_auto_request_candidates(tenant=self.tenant), [])
        self.assertEqual(self._card_requests().count(), 1)
        approved.refresh_from_db()
        self.assertEqual(approved.status, Request.STATUS_APPROVED)

    def test_deactivated_purpose_creates_nothing_and_warns(self):
        self.purpose_config.is_active = False
        self.purpose_config.save(update_fields=["is_active"])
        approved = self._approved_request()
        expense = self._expense()

        with self.assertLogs("apps.modules.requests.card_expense_auto_requests", level="WARNING") as logs:
            result = process_card_expense_auto_request(expense.pk)

        self.assertEqual(result.action, ACTION_SKIPPED)
        self.assertEqual(result.reason, f"назначение «{PURPOSE}» не активно для «Платежная карта»")
        self.assertTrue(any(f"config_id={self.config.pk}" in line for line in logs.output))
        self.assertEqual(self._card_requests().count(), 1)
        approved.refresh_from_db()
        self.assertEqual(approved.status, Request.STATUS_APPROVED)

    def test_hook_does_not_lock_expenses_of_cards_without_enabled_config(self):
        no_config = self._expense(wallet=self._second_card_wallet())
        own_first = self._expense(at=dt.datetime(2026, 11, 10, 9, 0, tzinfo=TASHKENT))
        own_second = self._expense(at=dt.datetime(2026, 11, 10, 11, 0, tzinfo=TASHKENT), amount="200.00")

        with patch.object(
            card_expense_auto_requests,
            "process_card_expense_auto_request",
            wraps=card_expense_auto_requests.process_card_expense_auto_request,
        ) as process, patch.object(
            card_expense_auto_requests, "system_user", wraps=card_expense_auto_requests.system_user
        ) as lookup:
            done = run_card_expense_auto_requests_hook(
                tenant=self.tenant, expense_ids=[no_config.pk, own_first.pk, own_second.pk]
            )

        self.assertEqual(done, 2)
        self.assertEqual([c.args[0] for c in process.call_args_list], [own_first.pk, own_second.pk])
        self.assertEqual(lookup.call_count, 1)
        self.assertFalse(self._card_requests().filter(expense_ref_id=no_config.pk).exists())


class BackfillCardExpenseAutoRequestsCommandTests(CardExpenseAutoRequestTestMixin, TestCase):
    def _run(self, *args):
        out = StringIO()
        call_command("backfill_card_expense_auto_requests", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_prints_candidate_and_changes_nothing(self):
        expense = self._expense()

        output = self._run(f"--tenant={self.tenant.pk}")

        self.assertIn(f"Будет создана заявка по расходу #{expense.pk} (150 000.00 UZS, 10.11.2026)", output)
        self.assertIn("Would close: 0, Would create: 1, Skipped: 0", output)
        self.assertEqual(self._card_requests().count(), 0)

    def test_apply_creates_and_second_apply_does_nothing(self):
        expense = self._expense()

        output = self._run("--tenant=cardauto", "--apply")

        self.assertIn("Closed: 0, Created: 1, Skipped: 0", output)
        req = self._card_requests().get()
        self.assertIn(f"Создана заявка #{req.pk} по расходу #{expense.pk}", output)
        second = self._run("--tenant=cardauto", "--apply")
        self.assertIn("Closed: 0, Created: 0, Skipped: 0", second)
        self.assertEqual(self._card_requests().count(), 1)

    def test_dry_run_is_empty_after_apply(self):
        self._approved_request()
        self._expense(at=dt.datetime(2026, 11, 10, 9, 0, tzinfo=TASHKENT))
        self._expense(at=dt.datetime(2026, 11, 10, 11, 0, tzinfo=TASHKENT))
        self._run("--tenant=cardauto", "--apply")

        output = self._run("--tenant=cardauto")

        self.assertIn("[cardauto] 0 card expenses without a request.", output)
        self.assertIn("Would close: 0, Would create: 0, Skipped: 0", output)

    def test_all_tenants_and_date_filter(self):
        other_tenant = Tenant.objects.create(name="Other", subdomain="cardautoother", is_active=True)
        other_wallet = get_or_create_corporate_wallet(tenant=other_tenant, currency="UZS")
        enable_card_auto_requests_for(other_tenant, updated_by=self.system)
        CardExpenseAutoRequestConfig.objects.create(
            tenant=other_tenant, wallet=other_wallet, is_enabled=True, payment_purpose=PURPOSE
        )
        self._expense(tenant=other_tenant, wallet=other_wallet)
        self._expense(at=dt.datetime(2026, 10, 20, 10, 0, tzinfo=TASHKENT))
        in_range = self._expense(at=dt.datetime(2026, 11, 10, 10, 0, tzinfo=TASHKENT))

        output = self._run("--all-tenants", "--date-from=2026-11-01", "--date-to=2026-11-30")

        self.assertIn("[cardauto] 1 card expenses without a request.", output)
        self.assertIn("[cardautoother] 1 card expenses without a request.", output)
        self.assertIn(f"по расходу #{in_range.pk}", output)
        self.assertIn("Would close: 0, Would create: 2, Skipped: 0", output)

    def test_without_tenant_raises(self):
        with self.assertRaises(CommandError):
            self._run()

    def test_cards_without_enabled_matching_config_are_not_candidates(self):
        self._expense(wallet=self._second_card_wallet())
        disabled_wallet = self._second_card_wallet()
        CardExpenseAutoRequestConfig.objects.create(
            tenant=self.tenant, wallet=disabled_wallet, is_enabled=False, payment_purpose=PURPOSE
        )
        self._expense(wallet=disabled_wallet)
        self.config.match_text = "taxi"
        self.config.save(update_fields=["match_text"])
        self._expense(note="Оплата рекламы")

        output = self._run("--tenant=cardauto")

        self.assertIn("[cardauto] 0 card expenses without a request.", output)

    def test_two_expenses_one_request_close_and_create(self):
        approved = self._approved_request()
        first = self._expense(at=dt.datetime(2026, 11, 10, 9, 0, tzinfo=TASHKENT))
        second = self._expense(at=dt.datetime(2026, 11, 10, 11, 0, tzinfo=TASHKENT))

        dry = self._run("--tenant=cardauto")

        self.assertIn(f"Будет закрыта заявка #{approved.pk} по расходу #{first.pk}", dry)
        self.assertIn(f"Будет создана заявка по расходу #{second.pk}", dry)
        self.assertIn("Would close: 1, Would create: 1, Skipped: 0", dry)
        approved.refresh_from_db()
        self.assertEqual(approved.status, Request.STATUS_APPROVED)
        self.assertEqual(self.payed_calls, [])

        applied = self._run("--tenant=cardauto", "--apply")

        self.assertIn(f"Закрыта заявка #{approved.pk} по расходу #{first.pk}", applied)
        self.assertIn("Closed: 1, Created: 1, Skipped: 0", applied)
        approved.refresh_from_db()
        self.assertEqual(approved.status, Request.STATUS_PAYED)
        self.assertEqual(approved.expense_ref_id, first.pk)
        self.assertEqual(self._card_requests().filter(expense_ref_id=second.pk).count(), 1)
        self.assertEqual(self.payed_calls, [approved.pk])

    def test_request_not_required_rule_is_reported_as_skipped(self):
        appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant, updated_by=self.system)
        RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg,
            payment_type=Request.PAYMENT_TYPE_CARD,
            is_enabled=True,
            request_not_required_rules=[{"field": "category", "operator": "eq", "value": "ops"}],
        )
        not_required = self._expense(payload={"category": "ops"})
        self._expense()

        output = self._run("--tenant=cardauto")

        self.assertIn("[cardauto] 2 card expenses without a request.", output)
        self.assertIn(
            f"Пропуск расхода #{not_required.pk}: по правилам компании заявка для расхода не нужна", output
        )
        self.assertIn("Would close: 0, Would create: 1, Skipped: 1", output)

    def test_system_user_is_looked_up_once_per_run(self):
        self._approved_request()
        self._expense(at=dt.datetime(2026, 11, 10, 9, 0, tzinfo=TASHKENT))
        self._expense(at=dt.datetime(2026, 11, 10, 11, 0, tzinfo=TASHKENT))

        with patch.object(
            card_expense_auto_requests, "system_user", side_effect=AssertionError("looked up per expense")
        ):
            dry = self._run("--tenant=cardauto")
            applied = self._run("--tenant=cardauto", "--apply")

        self.assertIn("Would close: 1, Would create: 1, Skipped: 0", dry)
        self.assertIn("Closed: 1, Created: 1, Skipped: 0", applied)

    def test_disabled_module_tenant_has_no_candidates(self):
        TenantModuleConfig.objects.filter(tenant=self.tenant, module_key="corporate_card").update(is_enabled=False)
        self._expense()

        output = self._run("--tenant=cardauto", "--apply")

        self.assertIn("[cardauto] 0 card expenses without a request.", output)
        self.assertEqual(self._card_requests().count(), 0)

    def test_without_system_user_raises(self):
        with patch(
            "apps.modules.requests.management.commands.backfill_card_expense_auto_requests.system_user",
            return_value=None,
        ):
            with self.assertRaises(CommandError):
                self._run("--tenant=cardauto")
