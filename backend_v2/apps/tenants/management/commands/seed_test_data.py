"""
Management command to seed local test data for every module.

Usage:
    python manage.py seed_test_data
    python manage.py seed_test_data --reset   # wipes existing seed data first

Docker Compose (local): после `migrate` команда вызывается автоматически — при пустой БД
создаётся полный демо-набор; при повторном старте без смены тома обновляются только
конфигурации (форма заявки, согласования, пользователи, токен бота).
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

User = get_user_model()

TENANT_SUBDOMAIN = "test"
TEST_TENANT_BOT_TOKEN = "7947271968:AAHSpJ-o5k4RBBAnUwwVfCCAXjfGgVmeJS0"
TEST_DDAVLET_TELEGRAM_ID = 1387986
MODULES = [
    "requests", "cash", "bank", "corporate_card", "payroll",
    "reports", "clients_debt", "budgets", "vendors", "contracts", "notes", "investments",
    "tasks",
]


class Command(BaseCommand):
    help = "Seed test data for local development (3-4 records per module)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing seed tenant and recreate everything from scratch",
        )

    def handle(self, *args, **options):
        from apps.tenants.models import Tenant

        if options["reset"]:
            self._reset_test_tenant()

        tenant, created = Tenant.objects.get_or_create(
            subdomain=TENANT_SUBDOMAIN,
            defaults={"name": "Test Company", "is_active": True},
        )
        tenant.set_telegram_bot_token(TEST_TENANT_BOT_TOKEN)
        tenant.save(update_fields=["telegram_bot_token_enc"])

        if created:
            self.stdout.write(f"Created tenant: {tenant}")
        else:
            self.stdout.write(self.style.WARNING(
                f"Tenant '{TENANT_SUBDOMAIN}' already exists — refreshing core settings "
                "(users, form/approval configs); demo rows only if DB still empty."
            ))

        admin, director, accountant, ddavlet = self._ensure_users_and_roles(tenant)
        self._ensure_modules(tenant)

        vendors = self._ensure_vendors(tenant, admin)

        categories = self._ensure_request_categories(tenant)
        self._ensure_request_form_configs(tenant, admin, ddavlet, vendors)
        self._ensure_request_approval_configs(tenant, admin, ddavlet)

        if self._tenant_has_demo_dataset(tenant):
            self.stdout.write(self.style.SUCCESS(
                "\n✓ Test tenant ready (demo dataset already present).\n"
                f"  Tenant subdomain : {TENANT_SUBDOMAIN}\n"
                f"  Admin login      : test_admin / testpass123\n"
                f"  Director login   : test_director / testpass123\n"
                f"  Accountant login : test_accountant / testpass123\n"
                f"  Approver login   : ddavlet / testpass123 (telegram_id={TEST_DDAVLET_TELEGRAM_ID})\n"
                f"  Admin panel      : http://test.localhost:8001/api/admin/\n"
                f"  API              : http://test.localhost:8001/api/\n"
            ))
            return

        cash_wallet, bank_wallet, card_wallet = self._create_wallets(tenant)
        self._seed_demo_requests(tenant, admin)
        self._seed_demo_cash(tenant, admin, cash_wallet)
        self._seed_demo_bank(tenant, admin, bank_wallet)
        self._seed_demo_corporate_card(tenant, admin, card_wallet)
        self._seed_demo_payroll(tenant)
        self._seed_demo_budgets(tenant, admin, categories)
        self._seed_demo_clients_debt(tenant, admin)
        self._seed_demo_investments(tenant, admin)
        self._seed_demo_notes(tenant, admin, director)
        self._seed_demo_tasks(tenant, admin, director, accountant)

        self.stdout.write(self.style.SUCCESS(
            "\n✓ Test data seeded successfully!\n"
            f"  Tenant subdomain : {TENANT_SUBDOMAIN}\n"
            f"  Admin login      : test_admin / testpass123\n"
            f"  Director login   : test_director / testpass123\n"
            f"  Accountant login : test_accountant / testpass123\n"
            f"  Approver login   : ddavlet / testpass123 (telegram_id={TEST_DDAVLET_TELEGRAM_ID})\n"
            f"  Admin panel      : http://test.localhost:8001/api/admin/\n"
            f"  API              : http://test.localhost:8001/api/\n"
        ))

    def _reset_test_tenant(self):
        from apps.tenants.models import Tenant
        from apps.modules.wallets.models import Wallet, CashRegister, BankAccount, CorporateCardAccount
        from apps.modules.cashier.models import CashExpense, CashRevenue
        from apps.modules.bank_expenses.models import BankExpense, BankRevenue
        from apps.modules.corporate_card.models import CardExpense, CardRevenue
        from apps.modules.requests.models import Request
        from apps.modules.payroll.models import PayrollDocument
        from apps.modules.budgets.models import Budget
        from apps.modules.clients_debt.models import ClientDebtSnapshot
        from apps.modules.investments.models import InvestReturn
        from apps.modules.notes.models import Note
        from apps.modules.vendors.models import Vendor
        from apps.modules.tasks.models import Task, TaskComment

        qs = Tenant.objects.filter(subdomain=TENANT_SUBDOMAIN)
        tenant_ids = list(qs.values_list("id", flat=True))
        if tenant_ids:
            TaskComment.objects.filter(task__tenant_id__in=tenant_ids).delete()
            Task.objects.filter(tenant_id__in=tenant_ids).delete()
            Request.objects.filter(tenant_id__in=tenant_ids).delete()
            CashExpense.objects.filter(tenant_id__in=tenant_ids).delete()
            CashRevenue.objects.filter(tenant_id__in=tenant_ids).delete()
            BankExpense.objects.filter(tenant_id__in=tenant_ids).delete()
            BankRevenue.objects.filter(tenant_id__in=tenant_ids).delete()
            CardExpense.objects.filter(tenant_id__in=tenant_ids).delete()
            CardRevenue.objects.filter(tenant_id__in=tenant_ids).delete()
            PayrollDocument.objects.filter(tenant_id__in=tenant_ids).delete()
            Budget.objects.filter(tenant_id__in=tenant_ids).delete()
            ClientDebtSnapshot.objects.filter(tenant_id__in=tenant_ids).delete()
            InvestReturn.objects.filter(tenant_id__in=tenant_ids).delete()
            Note.objects.filter(tenant_id__in=tenant_ids).delete()
            Vendor.objects.filter(tenant_id__in=tenant_ids).delete()
            Wallet.objects.filter(tenant_id__in=tenant_ids).delete()
            CashRegister.objects.filter(tenant_id__in=tenant_ids).delete()
            BankAccount.objects.filter(tenant_id__in=tenant_ids).delete()
            CorporateCardAccount.objects.filter(tenant_id__in=tenant_ids).delete()
            qs.delete()
        self.stdout.write(self.style.WARNING("Deleted existing test tenant."))

    def _tenant_has_demo_dataset(self, tenant) -> bool:
        from apps.modules.wallets.models import Wallet

        return Wallet.objects.filter(tenant=tenant).exists()

    def _ensure_users_and_roles(self, tenant):
        from apps.tenants.models import TenantMembership, TenantUserRole

        def make_user(username, role, password="testpass123", telegram_id=None):
            is_admin = role == TenantUserRole.ROLE_ADMIN
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={"email": f"{username}@test.local", "is_staff": is_admin, "is_superuser": is_admin},
            )
            if telegram_id is not None:
                user.telegram_chat_id = telegram_id
                user.telegram_from_id = telegram_id
            user.set_password(password)
            if telegram_id is not None:
                user.save(update_fields=["password", "telegram_chat_id", "telegram_from_id"])
            else:
                user.save(update_fields=["password"])
            TenantMembership.objects.get_or_create(tenant=tenant, user=user, defaults={"is_active": True})
            TenantUserRole.objects.get_or_create(tenant=tenant, user=user, role=role)
            return user

        admin = make_user("test_admin", TenantUserRole.ROLE_ADMIN)
        director = make_user("test_director", TenantUserRole.ROLE_DIRECTOR)
        accountant = make_user("test_accountant", TenantUserRole.ROLE_ACCOUNTANT)
        ddavlet = make_user(
            "ddavlet",
            TenantUserRole.ROLE_APPROVER,
            telegram_id=TEST_DDAVLET_TELEGRAM_ID,
        )
        TenantUserRole.objects.get_or_create(
            tenant=tenant,
            user=ddavlet,
            role=TenantUserRole.ROLE_REQUESTER,
        )

        self.stdout.write(
            "  Users: "
            f"{admin.username} / {director.username} / {accountant.username} / {ddavlet.username} "
            "(password: testpass123)"
        )
        return admin, director, accountant, ddavlet

    def _ensure_modules(self, tenant):
        from apps.tenants.models import TenantModuleConfig

        for key in MODULES:
            TenantModuleConfig.objects.get_or_create(tenant=tenant, module_key=key, defaults={"is_enabled": True})
            TenantModuleConfig.objects.filter(tenant=tenant, module_key=key).update(is_enabled=True)

        self.stdout.write(f"  Modules enabled: {', '.join(MODULES)}")

    def _ensure_vendors(self, tenant, admin):
        from apps.modules.vendors.models import Vendor

        vendor_rows = [
            ("Касса Ромашка", Vendor.KIND_CASH, "", ""),
            ("Касса АвтоДел", Vendor.KIND_CASH, "", ""),
            ("ООО ТехСервис", Vendor.KIND_TRANSFER, "301234567", "20208000100100000001"),
            ("ИП Иванов", Vendor.KIND_TRANSFER, "309876543", "20208000100100000002"),
        ]
        vendors = []
        for name, kind, inn, account_number in vendor_rows:
            v, created = Vendor.objects.get_or_create(
                tenant=tenant,
                name=name,
                defaults={
                    "kind": kind,
                    "inn": inn or None,
                    "account_number": account_number or None,
                    "created_by": admin,
                },
            )
            if not created:
                v.kind = kind
                v.inn = inn or None
                v.account_number = account_number or None
                v.save(update_fields=["kind", "inn", "account_number"])
            vendors.append(v)

        self.stdout.write(f"  Vendors: {len(vendors)} ensured")
        return vendors

    def _ensure_request_categories(self, tenant):
        from apps.modules.requests.models import RequestCategory

        categories = []
        for cat_name in ["IT", "Marketing", "HR"]:
            c, _ = RequestCategory.objects.get_or_create(
                tenant=tenant,
                name=cat_name,
                defaults={"is_active": True},
            )
            if not c.is_active:
                c.is_active = True
                c.save(update_fields=["is_active"])
            categories.append(c)
        return categories

    def _ensure_request_form_configs(self, tenant, admin, ddavlet, vendors):
        from apps.modules.requests.models import (
            Request,
            RequestFormConfig,
            RequestFormPaymentTypeConfig,
            RequestFormPaymentTypeRequester,
            RequestFormPaymentTypeVendor,
            RequestPaymentPurposeConfig,
        )
        from apps.modules.vendors.models import Vendor

        form_cfg, _ = RequestFormConfig.objects.get_or_create(tenant=tenant, defaults={"updated_by": admin})
        form_cfg.updated_by = admin
        form_cfg.save(update_fields=["updated_by"])

        cash_vendor = next((v for v in vendors if v.kind == Vendor.KIND_CASH), None)
        transfer_vendor = next((v for v in vendors if v.kind == Vendor.KIND_TRANSFER), None)
        payer_by_type = {
            Request.PAYMENT_TYPE_CASH: "Test Cash LLC",
            Request.PAYMENT_TYPE_TRANSFER: "Test Transfer LLC",
            Request.PAYMENT_TYPE_TOPUP: "Test Topup LLC",
            Request.PAYMENT_TYPE_CARD: "Test Card LLC",
            Request.PAYMENT_TYPE_PAYROLL: "Test Payroll LLC",
        }
        purpose_by_type = {
            Request.PAYMENT_TYPE_CASH: ("Хозрасходы", "IT"),
            Request.PAYMENT_TYPE_TRANSFER: ("Оплата поставщику", "Marketing"),
            Request.PAYMENT_TYPE_TOPUP: ("Пополнение счета", "HR"),
            Request.PAYMENT_TYPE_CARD: ("Онлайн подписки", "IT"),
            Request.PAYMENT_TYPE_PAYROLL: ("Начисление зарплаты", "HR"),
        }

        for payment_type, _label in Request.PAYMENT_TYPE_CHOICES:
            is_cash = payment_type == Request.PAYMENT_TYPE_CASH
            default_vendor = cash_vendor if is_cash else transfer_vendor
            default_purpose_name, default_category = purpose_by_type[payment_type]
            pt_cfg, _ = RequestFormPaymentTypeConfig.objects.get_or_create(
                config=form_cfg,
                payment_type=payment_type,
                defaults={
                    "is_enabled": True,
                    "default_title": "Тестовая заявка",
                    "default_company_payer": payer_by_type[payment_type],
                    "default_description": "Автозаполнение для локальных тестов",
                    "default_amount": Decimal("100000"),
                    "default_currency": Request.CURRENCY_UZS,
                    "default_urgency": Request.URGENCY_NORMAL,
                    "default_billing_days_offset": 0,
                    "default_payment_purpose": default_purpose_name,
                    "default_vendor": default_vendor,
                    "contracts_required": False,
                },
            )
            pt_cfg.is_enabled = True
            pt_cfg.default_title = "Тестовая заявка"
            pt_cfg.default_company_payer = payer_by_type[payment_type]
            pt_cfg.default_description = "Автозаполнение для локальных тестов"
            pt_cfg.default_amount = Decimal("100000")
            pt_cfg.default_currency = Request.CURRENCY_UZS
            pt_cfg.default_urgency = Request.URGENCY_NORMAL
            pt_cfg.default_billing_days_offset = 0
            pt_cfg.default_payment_purpose = default_purpose_name
            pt_cfg.default_vendor = default_vendor
            pt_cfg.contracts_required = False
            pt_cfg.save()

            RequestFormPaymentTypeRequester.objects.get_or_create(payment_type_config=pt_cfg, user=ddavlet)
            if default_vendor:
                RequestFormPaymentTypeVendor.objects.get_or_create(
                    payment_type_config=pt_cfg,
                    vendor=default_vendor,
                )

            purpose, _ = RequestPaymentPurposeConfig.objects.get_or_create(
                payment_type_config=pt_cfg,
                name=default_purpose_name,
                defaults={"category": default_category, "is_active": True},
            )
            if purpose.category != default_category or not purpose.is_active:
                purpose.category = default_category
                purpose.is_active = True
                purpose.save(update_fields=["category", "is_active"])

        self.stdout.write("  Request form config: defaults + purposes ensured for all payment types")

    def _ensure_request_approval_configs(self, tenant, admin, ddavlet):
        from apps.modules.requests.models import (
            Approval,
            Request,
            RequestApprovalConfig,
            RequestApprovalPaymentTypeConfig,
            RequestApprovalStepApproverConfig,
            RequestApprovalStepConfig,
        )

        approval_cfg, _ = RequestApprovalConfig.objects.get_or_create(tenant=tenant, defaults={"updated_by": admin})
        approval_cfg.updated_by = admin
        approval_cfg.save(update_fields=["updated_by"])

        for payment_type, _label in Request.PAYMENT_TYPE_CHOICES:
            pt_cfg, _ = RequestApprovalPaymentTypeConfig.objects.get_or_create(
                config=approval_cfg,
                payment_type=payment_type,
                defaults={"is_enabled": True},
            )
            pt_cfg.is_enabled = True
            pt_cfg.save(update_fields=["is_enabled"])

            step_defs = [
                (1, Approval.STEP_TYPE_SERIAL, RequestApprovalStepConfig.PAYMENT_ACTION_MODE_CALLBACK),
                (2, Approval.STEP_TYPE_SERIAL, RequestApprovalStepConfig.PAYMENT_ACTION_MODE_CALLBACK),
                (3, Approval.STEP_TYPE_PAYMENT, RequestApprovalStepConfig.PAYMENT_ACTION_MODE_CREATE),
            ]
            for step, step_type, payment_action_mode in step_defs:
                step_cfg, _ = RequestApprovalStepConfig.objects.get_or_create(
                    payment_type_config=pt_cfg,
                    step=step,
                    defaults={
                        "step_type": step_type,
                        "is_enabled": True,
                        "payment_action_mode": payment_action_mode,
                    },
                )
                step_cfg.step_type = step_type
                step_cfg.is_enabled = True
                step_cfg.payment_action_mode = payment_action_mode
                step_cfg.save(update_fields=["step_type", "is_enabled", "payment_action_mode"])
                RequestApprovalStepApproverConfig.objects.get_or_create(
                    step_config=step_cfg,
                    approver_user=ddavlet,
                )

        self.stdout.write("  Approval config: 3-step pipeline ensured for all payment types")

    def _create_wallets(self, tenant):
        from apps.modules.wallets.models import Wallet, CashRegister, BankAccount, CorporateCardAccount

        cash_register = CashRegister.objects.create(tenant=tenant, currency="UZS", name="Основная касса")
        cash_wallet = Wallet.objects.create(
            tenant=tenant, wallet_type="cash", currency="UZS", cash_register=cash_register,
        )
        bank_account = BankAccount.objects.create(tenant=tenant, label="Основной счёт")
        bank_wallet = Wallet.objects.create(
            tenant=tenant, wallet_type="bank", currency="UZS", bank_account=bank_account,
        )
        card_account = CorporateCardAccount.objects.create(tenant=tenant, currency="USD", label="Корпоративная карта")
        card_wallet = Wallet.objects.create(
            tenant=tenant, wallet_type="corporate_card", currency="USD", corporate_card_account=card_account,
        )
        self.stdout.write("  Wallets: cash/UZS, bank/UZS, card/USD")
        return cash_wallet, bank_wallet, card_wallet

    def _seed_demo_requests(self, tenant, admin):
        from apps.modules.requests.models import Request

        today = date.today()
        request_data = [
            ("Ноутбук для разработчика", "IT", Decimal("5000000"), "UZS", Request.STATUS_APPROVED, today),
            ("Реклама в Instagram", "Marketing", Decimal("1500000"), "UZS", Request.STATUS_PAYED, today - timedelta(days=15)),
            ("Корпоратив на НГ", "HR", Decimal("3000000"), "UZS", Request.STATUS_DRAFT, today - timedelta(days=5)),
            ("Подписка GitHub Teams", "IT", Decimal("200"), "USD", Request.STATUS_APPROVED, today - timedelta(days=2)),
        ]
        requests = []
        for title, cat_name, amount, currency, status, bdate in request_data:
            r = Request.objects.create(
                tenant=tenant,
                created_by=admin,
                requester=admin,
                title=title,
                category=cat_name,
                amount=amount,
                currency=currency,
                status=status,
                billing_date=bdate,
                payment_type=Request.PAYMENT_TYPE_CASH,
            )
            requests.append(r)
        self.stdout.write(f"  Requests: {len(requests)} created (categories: IT, Marketing, HR)")

    def _seed_demo_cash(self, tenant, admin, cash_wallet):
        from apps.modules.cashier.models import CashExpense, CashRevenue

        now = timezone.now()
        for i, (title, amount) in enumerate([("Канцтовары", 50000), ("Такси", 30000), ("Обед команды", 120000), ("Аренда зала", 200000)]):
            dt = now - timedelta(days=i)
            CashExpense.objects.create(
                tenant=tenant, created_by=admin,
                external_id=f"cash-exp-{i+1}",
                title=title, amount=amount, currency="UZS",
                wallet=cash_wallet, confirmed=True,
                expense_at=dt, expense_year=dt.year,
                expense_month=dt.month, expense_day=dt.day,
                note="", payload={},
            )
        for i, (operation, total) in enumerate([("Возврат от клиента", 100000), ("Пополнение кассы", 500000), ("Возврат подотчёта", 75000)]):
            CashRevenue.objects.create(
                tenant=tenant, created_by=admin,
                external_id=f"cash-rev-{i+1}",
                operation=operation, total_sum=total,
                wallet=cash_wallet, confirmed=True, payload={},
            )
        self.stdout.write("  Cash: 4 expenses, 3 revenues")

    def _seed_demo_bank(self, tenant, admin, bank_wallet):
        from apps.modules.bank_expenses.models import BankExpense, BankRevenue

        now = timezone.now()
        for i, (purpose, amount) in enumerate([("Оплата поставщику", 2000000), ("Аренда офиса", 3500000), ("Зарплата", 10000000), ("Коммунальные услуги", 450000)]):
            dt = now - timedelta(days=i)
            BankExpense.objects.create(
                tenant=tenant, created_by=admin,
                row_no=i + 1, doc_no=f"DOC-{1000+i}",
                doc_date=dt.date(), process_date=dt.date(),
                expense_year=dt.year, expense_month=dt.month, expense_day=dt.day,
                payment_purpose=purpose, debit_turnover=amount,
                wallet=bank_wallet,
            )
        for i, (purpose, amount) in enumerate([("Поступление от клиента", 5000000), ("Возврат переплаты", 300000), ("Прочие поступления", 150000)]):
            dt = now - timedelta(days=i)
            BankRevenue.objects.create(
                tenant=tenant, created_by=admin,
                doc_no=f"REV-{2000+i}", doc_date=dt.date(), process_date=dt.date(),
                account_name=f"ООО Клиент {i+1}", inn=f"30230000{i}",
                account_no=f"2020800{i}000000000", mfo=f"0093{i}",
                payment_purpose=purpose, kredit_turnover=amount,
                wallet=bank_wallet,
            )
        self.stdout.write("  Bank: 4 expenses, 3 revenues")

    def _seed_demo_corporate_card(self, tenant, admin, card_wallet):
        from apps.modules.corporate_card.models import CardExpense, CardRevenue

        now = timezone.now()
        for i, (title, amount) in enumerate([("Uber business", 45), ("AWS services", 120), ("Zoom subscription", 15), ("Adobe license", 55)]):
            dt = now - timedelta(days=i)
            CardExpense.objects.create(
                tenant=tenant, created_by=admin,
                title=title, amount=amount, currency="USD",
                wallet=card_wallet, expense_at=dt, payload={},
            )
        for i in range(3):
            dt = now - timedelta(days=i)
            CardRevenue.objects.create(
                tenant=tenant, created_by=admin,
                amount=Decimal("500"), currency="USD",
                wallet=card_wallet, revenue_at=dt,
            )
        self.stdout.write("  Corporate card: 4 expenses, 3 revenues")

    def _seed_demo_payroll(self, tenant):
        from apps.modules.payroll.models import PayrollDocument, PayrollLine

        for doc_num in range(1, 3):
            doc = PayrollDocument.objects.create(
                tenant=tenant, doc_id=f"PR-2026-0{doc_num}",
            )
            p_start = date(2026, doc_num, 1)
            p_end = date(2026, doc_num, 28)
            for line_no, (employee, amount) in enumerate([
                ("Иванов И.И.", Decimal("3000000")),
                ("Петрова А.С.", Decimal("2500000")),
                ("Сидоров В.В.", Decimal("2800000")),
            ], start=1):
                PayrollLine.objects.create(
                    document=doc, line_no=line_no,
                    employee=employee, item="Оклад",
                    sum=amount, days_plan=22, days_fact=22,
                    period_start=p_start, period_end=p_end,
                )
        self.stdout.write("  Payroll: 2 documents × 3 lines")

    def _seed_demo_budgets(self, tenant, admin, categories):
        from apps.modules.budgets.models import Budget

        budget_data = [
            ("IT бюджет", categories[0], Budget.PERIOD_MONTHLY, Decimal("10000000"), "UZS"),
            ("Маркетинг Q2", categories[1], Budget.PERIOD_QUARTERLY, Decimal("5000000"), "UZS"),
            ("HR годовой", categories[2], Budget.PERIOD_YEARLY, Decimal("30000000"), "UZS"),
            ("IT подписки (USD)", categories[0], Budget.PERIOD_MONTHLY, Decimal("1000"), "USD"),
        ]
        for name, cat, period_type, limit, currency in budget_data:
            Budget.objects.create(
                tenant=tenant, name=name, category=cat,
                period_type=period_type, limit_amount=limit,
                currency=currency, created_by=admin,
            )
        self.stdout.write(f"  Budgets: {len(budget_data)} created")

    def _seed_demo_clients_debt(self, tenant, admin):
        from apps.modules.clients_debt.models import ClientDebtSnapshot

        for i, (client, debt) in enumerate([("ООО АльфаТорг", 1500000), ("ИП Петров", 750000), ("ТехСервис Плюс", 3200000)]):
            ClientDebtSnapshot.objects.create(
                tenant=tenant,
                snapshot_at=timezone.now() - timedelta(days=i * 30),
                created_by=admin,
                client=client,
                debt_sum=Decimal(str(debt)),
            )
        self.stdout.write("  Clients debt: 3 snapshots")

    def _seed_demo_investments(self, tenant, admin):
        from apps.modules.investments.models import InvestReturn

        today = date.today()
        for i, (amount, inv_type, recipient) in enumerate([
            (Decimal("10000000"), InvestReturn.ReturnType.DIVIDEND, InvestReturn.Recipient.INVESTOR),
            (Decimal("7500000"), InvestReturn.ReturnType.DIVIDEND, InvestReturn.Recipient.PARTNER),
            (Decimal("5000000"), InvestReturn.ReturnType.INTEREST, InvestReturn.Recipient.INVESTOR),
            (Decimal("3000000"), InvestReturn.ReturnType.PRINCIPAL, InvestReturn.Recipient.PARTNER),
        ]):
            payout_dt = today - timedelta(days=i * 10)
            InvestReturn.objects.create(
                tenant=tenant,
                created_by=admin,
                date=payout_dt,
                billing_date=payout_dt.replace(day=1),
                sum=amount,
                sum_uzs=amount,
                currency="UZS",
                type=inv_type,
                recipient=recipient,
                comment="",
                confirmed=False,
            )
        self.stdout.write("  Investments: 4 invest returns")

    def _seed_demo_notes(self, tenant, admin, director):
        from apps.modules.notes.models import Note

        for i, (msg, target_type) in enumerate([
            ("Проверить оплату по заявке #1", Note.TARGET_REQUEST),
            ("Согласовать бюджет на Q3", Note.TARGET_CASH),
            ("Обновить реквизиты поставщика ООО Ромашка", Note.TARGET_BANK),
        ]):
            Note.objects.create(
                tenant=tenant, created_by=admin,
                recipient_user=director,
                target_type=target_type, target_id=i + 1,
                message=msg,
            )
        self.stdout.write("  Notes: 3 created")

    def _seed_demo_tasks(self, tenant, admin, director, accountant):
        from apps.modules.tasks.models import Task, TaskComment

        now = timezone.now()

        task_rows = [
            # (title, description, assignee, status, source_type, completed_at, days_ago)
            (
                "Согласовать договор с ООО ТехСервис",
                "Проверить реквизиты и условия. Срок — до конца недели.",
                accountant,
                Task.STATUS_NEW,
                Task.SOURCE_MANUAL,
                None,
                0,
            ),
            (
                "Проверить остаток по корпоративной карте",
                "Сверить фактический остаток со сводкой за апрель.",
                accountant,
                Task.STATUS_NEW,
                Task.SOURCE_MANUAL,
                None,
                1,
            ),
            (
                "Подготовить отчёт за май 2026",
                "Включить все статьи расходов: касса, банк, карта.",
                director,
                Task.STATUS_NEW,
                Task.SOURCE_MANUAL,
                None,
                2,
            ),
            (
                "Оформить авансовый отчёт — командировка Ташкент",
                "Приложить чеки и посадочные талоны.",
                accountant,
                Task.STATUS_IN_PROGRESS,
                Task.SOURCE_MANUAL,
                None,
                3,
            ),
            (
                "Обновить реквизиты контрагента ИП Иванов",
                "Новый расчётный счёт с 15 мая. Уточнить у менеджера.",
                admin,
                Task.STATUS_IN_PROGRESS,
                Task.SOURCE_MANUAL,
                None,
                4,
            ),
            (
                "Согласовать бюджет на маркетинг Q3",
                "",
                director,
                Task.STATUS_IN_PROGRESS,
                Task.SOURCE_MANUAL,
                None,
                5,
            ),
            (
                "Выгрузить банковскую выписку за апрель",
                "Отправить главному бухгалтеру до 5-го числа.",
                accountant,
                Task.STATUS_DONE,
                Task.SOURCE_MANUAL,
                now - timedelta(days=2),
                10,
            ),
            (
                "Проверить оплату по заявке #1",
                "Заявка на ноутбук для разработчика — подтвердить списание.",
                admin,
                Task.STATUS_DONE,
                Task.SOURCE_REQUEST_APPROVED,
                now - timedelta(days=5),
                15,
            ),
            (
                "Закрыть подписку на неиспользуемый сервис",
                "",
                admin,
                Task.STATUS_DONE,
                Task.SOURCE_MANUAL,
                now - timedelta(days=8),
                20,
            ),
        ]

        created_tasks = []
        for title, description, assignee, status, source_type, completed_at, days_ago in task_rows:
            task = Task.objects.create(
                tenant=tenant,
                assignee=assignee,
                created_by=admin,
                title=title,
                description=description,
                status=status,
                source_type=source_type,
                completed_at=completed_at,
            )
            if days_ago:
                Task.objects.filter(pk=task.pk).update(
                    created_at=now - timedelta(days=days_ago),
                    updated_at=now - timedelta(days=days_ago),
                )
            created_tasks.append(task)

        # Add comments to first in-progress task (accountant task) to demo the admin badge
        task_with_comments = created_tasks[3]  # "Оформить авансовый отчёт"
        comment1 = TaskComment.objects.create(
            task=task_with_comments,
            author=admin,
            body="Не забудьте приложить оригиналы чеков, а не ксерокопии.",
        )
        TaskComment.objects.filter(pk=comment1.pk).update(
            created_at=now - timedelta(hours=5),
        )
        Task.objects.filter(pk=task_with_comments.pk).update(
            last_admin_comment_at=now - timedelta(hours=5),
        )

        # Add a comment from the assignee on a new task (no badge — non-admin comment)
        task_with_reply = created_tasks[0]  # "Согласовать договор"
        comment2 = TaskComment.objects.create(
            task=task_with_reply,
            author=accountant,
            body="Запросил договор у менеджера, жду ответа.",
        )
        TaskComment.objects.filter(pk=comment2.pk).update(
            created_at=now - timedelta(hours=2),
        )

        self.stdout.write(
            f"  Tasks: {len(created_tasks)} created "
            f"(3 new, 3 in-progress, 3 done | 2 with comments)"
        )
