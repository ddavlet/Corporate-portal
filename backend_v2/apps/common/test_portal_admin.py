from django.apps import apps
from django.contrib import admin
from django.test import SimpleTestCase

# Models that are not portal business tables (or duplicate unmanaged projections).
_SKIP_UNREGISTERED = {
    "accounts.OtpChallenge",
    "requests.UserRequestApproval",
    "tenants.TenantMembership",
    "tenants.TenantUserPreference",
}

_APP_VERBOSE_NAMES = {
    "accounts": "Пользователи",
    "tenants": "Компания",
    "requests": "Заявки",
    "tasks": "Задачи",
    "cashier": "Касса",
    "bank_expenses": "Банк",
    "corporate_card": "Корпоративная карта",
    "payroll": "Начисления ЗП",
    "reports": "Отчеты",
    "investments": "Инвестиции",
    "clients_debt": "Долги клиентов",
    "budgets": "Бюджеты",
    "contracts": "Договоры",
    "wallets": "Кошельки и счета",
    "vendors": "Поставщики",
    "notes": "Комментарии",
    "feedback": "Обратная связь",
    "telegram_approvals": "Telegram",
    "n8n_integration": "Связь с n8n",
    "mcp_server": "Вопросы в ИИ",
    "mcp_oauth": "Вопросы в ИИ",
}

_MODEL_LABELS = {
    "requests.Request": ("Заявка", "Заявки"),
    "cashier.CashExpense": ("Касса — расход", "Касса — расходы"),
    "cashier.CashRevenue": ("Касса — доход", "Касса — доходы"),
    "bank_expenses.BankExpense": ("Банк — расход", "Банк — расходы"),
    "bank_expenses.BankRevenue": ("Банк — доход", "Банк — доходы"),
    "corporate_card.CardExpense": ("Корпоративная карта — расход", "Корпоративная карта — расходы"),
    "corporate_card.CardRevenue": ("Корпоративная карта — доход", "Корпоративная карта — доходы"),
    "tasks.Task": ("Задача", "Задачи"),
    "payroll.PayrollDocument": ("Начисление ЗП", "Начисления ЗП"),
    "investments.InvestReturn": ("Выплата", "Выплаты"),
    "investments.InvestPayoutSchedule": ("Расписание выплат", "Расписание выплат"),
    "investments.ProjectInvestment": ("Заявка на вложение", "Заявки на вложение"),
    "clients_debt.ClientDebtSnapshot": ("Долг клиента", "Долги клиентов"),
    "budgets.Budget": ("Бюджет", "Бюджеты"),
    "contracts.Contract": ("Договор", "Договоры"),
    "vendors.Vendor": ("Поставщик", "Поставщики"),
    "feedback.PortalFeedback": ("Обратная связь", "Обратная связь"),
    "telegram_approvals.TenantTelegramChat": ("Telegram-группа", "Telegram-группы"),
    "wallets.CashRegister": ("Касса (кошелёк)", "Кассы"),
    "reports.TenantReportSettings": ("Настройки отчётов", "Настройки отчётов"),
}


def _model_key(model) -> str:
    return f"{model._meta.app_label}.{model.__name__}"


class PortalAdminRegistrationTests(SimpleTestCase):
    def test_app_verbose_names_match_portal(self):
        for label, expected in _APP_VERBOSE_NAMES.items():
            self.assertEqual(apps.get_app_config(label).verbose_name, expected, label)

    def test_managed_portal_models_are_registered(self):
        missing = []
        for model in apps.get_models():
            if model._meta.app_label not in _APP_VERBOSE_NAMES:
                continue
            if not model._meta.managed:
                continue
            key = _model_key(model)
            if key in _SKIP_UNREGISTERED:
                continue
            if model not in admin.site._registry:
                missing.append(key)
        self.assertEqual(missing, [])

    def test_model_admin_labels_match_portal(self):
        for key, (singular, plural) in _MODEL_LABELS.items():
            app_label, model_name = key.split(".")
            model = apps.get_model(app_label, model_name)
            self.assertIn(model, admin.site._registry, key)
            self.assertEqual(str(model._meta.verbose_name), singular, key)
            self.assertEqual(str(model._meta.verbose_name_plural), plural, key)
