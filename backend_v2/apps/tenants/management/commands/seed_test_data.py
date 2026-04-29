"""
Management command to seed local test data for every module.

Usage:
    python manage.py seed_test_data
    python manage.py seed_test_data --reset   # wipes existing seed data first
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

User = get_user_model()

TENANT_SUBDOMAIN = "test"
MODULES = [
    "requests", "cash", "bank", "corporate_card", "payroll",
    "reports", "clients_debt", "budgets", "vendors", "contracts", "notes", "investments",
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
        from apps.tenants.models import (
            Tenant, TenantMembership, TenantModuleConfig, TenantUserRole,
        )

        if options["reset"]:
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
            qs = Tenant.objects.filter(subdomain=TENANT_SUBDOMAIN)
            tenant_ids = list(qs.values_list("id", flat=True))
            if tenant_ids:
                # Delete in dependency order (protected FKs first)
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

        tenant, created = Tenant.objects.get_or_create(
            subdomain=TENANT_SUBDOMAIN,
            defaults={"name": "Test Company", "is_active": True},
        )
        if not created:
            self.stdout.write(self.style.WARNING(
                f"Tenant '{TENANT_SUBDOMAIN}' already exists — skipping (use --reset to wipe)."
            ))
            return

        self.stdout.write(f"Created tenant: {tenant}")

        # ── Users ────────────────────────────────────────────────────────────
        def make_user(username, role, password="testpass123"):
            is_admin = role == TenantUserRole.ROLE_ADMIN
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={"email": f"{username}@test.local", "is_staff": is_admin, "is_superuser": is_admin},
            )
            user.set_password(password)
            user.save(update_fields=["password"])
            TenantMembership.objects.get_or_create(tenant=tenant, user=user, defaults={"is_active": True})
            TenantUserRole.objects.get_or_create(tenant=tenant, user=user, defaults={"role": role})
            return user

        admin = make_user("test_admin", TenantUserRole.ROLE_ADMIN)
        director = make_user("test_director", TenantUserRole.ROLE_DIRECTOR)
        accountant = make_user("test_accountant", TenantUserRole.ROLE_ACCOUNTANT)

        self.stdout.write(f"  Users: {admin.username} / {director.username} / {accountant.username}  (password: testpass123)")

        # ── Enable all modules ───────────────────────────────────────────────
        for key in MODULES:
            TenantModuleConfig.objects.get_or_create(tenant=tenant, module_key=key, defaults={"is_enabled": True})

        self.stdout.write(f"  Modules enabled: {', '.join(MODULES)}")

        # ── Wallets ──────────────────────────────────────────────────────────
        from apps.modules.wallets.models import (
            Wallet, CashRegister, BankAccount, CorporateCardAccount,
        )
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

        # ── Vendors ──────────────────────────────────────────────────────────
        from apps.modules.vendors.models import Vendor
        vendors = []
        for name, kind in [("ООО Ромашка", "legal"), ("ИП Иванов", "individual"), ("ТехСервис", "legal"), ("АвтоДел", "individual")]:
            v = Vendor.objects.create(tenant=tenant, name=name, kind=kind, created_by=admin)
            vendors.append(v)
        self.stdout.write(f"  Vendors: {len(vendors)} created")

        # ── Requests ─────────────────────────────────────────────────────────
        from apps.modules.requests.models import (
            Request, RequestCategory, RequestFormConfig,
            RequestApprovalConfig,
        )
        categories = []
        for cat_name in ["IT", "Marketing", "HR"]:
            c = RequestCategory.objects.create(tenant=tenant, name=cat_name, is_active=True)
            categories.append(c)

        RequestFormConfig.objects.get_or_create(tenant=tenant, defaults={"updated_by": admin})
        RequestApprovalConfig.objects.get_or_create(tenant=tenant, defaults={"updated_by": admin})

        today = date.today()
        request_data = [
            ("Ноутбук для разработчика", "IT", Decimal("5000000"), "UZS", Request.STATUS_APPROVED, today),
            ("Реклама в Instagram", "Marketing", Decimal("1500000"), "UZS", Request.STATUS_PAYED, today - timedelta(days=15)),
            ("Корпоратив на НГ", "HR", Decimal("3000000"), "UZS", Request.STATUS_DRAFT, today - timedelta(days=5)),
            ("Подписка GitHub Teams", "IT", Decimal("200"), "USD", Request.STATUS_APPROVED, today - timedelta(days=2)),
        ]
        requests = []
        for title, cat, amount, currency, status, bdate in request_data:
            r = Request.objects.create(
                tenant=tenant,
                created_by=admin,
                requester=admin,
                title=title,
                category=cat,
                amount=amount,
                currency=currency,
                status=status,
                billing_date=bdate,
                payment_type=Request.PAYMENT_TYPE_CASH,
            )
            requests.append(r)
        self.stdout.write(f"  Requests: {len(requests)} created (categories: IT, Marketing, HR)")

        # ── Cash ─────────────────────────────────────────────────────────────
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

        # ── Bank ─────────────────────────────────────────────────────────────
        from apps.modules.bank_expenses.models import BankExpense, BankRevenue
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

        # ── Corporate Card ───────────────────────────────────────────────────
        from apps.modules.corporate_card.models import CardExpense, CardRevenue
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

        # ── Payroll ──────────────────────────────────────────────────────────
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

        # ── Budgets ──────────────────────────────────────────────────────────
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

        # ── Clients Debt ─────────────────────────────────────────────────────
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

        # ── Investments ──────────────────────────────────────────────────────
        from apps.modules.investments.models import InvestReturn
        for i, (amount, inv_type, recipient) in enumerate([
            (Decimal("10000000"), InvestReturn.ReturnType.DIVIDEND, InvestReturn.Recipient.INVESTOR),
            (Decimal("7500000"), InvestReturn.ReturnType.DIVIDEND, InvestReturn.Recipient.PARTNER),
            (Decimal("5000000"), InvestReturn.ReturnType.INTEREST, InvestReturn.Recipient.INVESTOR),
            (Decimal("3000000"), InvestReturn.ReturnType.PRINCIPAL, InvestReturn.Recipient.PARTNER),
        ]):
            InvestReturn.objects.create(
                tenant=tenant, created_by=admin,
                date=today - timedelta(days=i * 10),
                sum=amount, type=inv_type, recipient=recipient,
            )
        self.stdout.write("  Investments: 4 invest returns")

        # ── Notes ────────────────────────────────────────────────────────────
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

        self.stdout.write(self.style.SUCCESS(
            "\n✓ Test data seeded successfully!\n"
            f"  Tenant subdomain : {TENANT_SUBDOMAIN}\n"
            f"  Admin login      : test_admin / testpass123\n"
            f"  Director login   : test_director / testpass123\n"
            f"  Accountant login : test_accountant / testpass123\n"
            f"  Admin panel      : http://test.localhost:8001/api/admin/\n"
            f"  API              : http://test.localhost:8001/api/\n"
        ))
