from rest_framework import serializers
from django.urls import reverse

from apps.modules.requests.models import Request
from apps.modules.cashier.models import CashExpense
from apps.modules.bank_expenses.models import BankExpense
from apps.tenants.permissions import has_effective_module_access


class PortalRequestSerializer(serializers.ModelSerializer):
    expense_link = serializers.SerializerMethodField()

    class Meta:
        model = Request
        fields = [
            "id",
            "expense_id",
            "expense_link",
            "company_payer",
            "category",
            "vendor",
            "title",
            "description",
            "amount",
            "currency",
            "payment_type",
            "urgency",
            "requester",
            "payment_purpose",
            "submitted_at",
            "status",
            "payed_at",
            "file_link",
            "expense_year",
            "expense_month",
            "expense_day",
            "billing_date",
        ]
        read_only_fields = ["id", "expense_link"]

    def get_expense_link(self, obj):
        request = self.context.get("request")
        tenant = getattr(request, "tenant", None)
        user = getattr(request, "user", None)

        if not getattr(obj, "expense_id", None):
            return None

        # expense_id is stored as varchar(20) and is expected to be numeric for local modules.
        try:
            numeric_id = int(str(obj.expense_id))
        except (TypeError, ValueError):
            numeric_id = None

        # If cash module is effectively enabled, resolve `expense_id` as a local cash expense.
        if numeric_id is not None and has_effective_module_access(user=user, tenant=tenant, module_key="cash"):
            cash_expense = CashExpense.objects.filter(tenant=tenant, id=numeric_id).first()
            if cash_expense:
                rel = reverse("cash-expenses-detail", kwargs={"pk": cash_expense.id})
                url = request.build_absolute_uri(rel) if request else rel
                return {
                    "module": "cash",
                    "expense_type": "cash",
                    "id": cash_expense.id,
                    "url": url,
                }

        # If cashier didn't match, try bank module (independent via module toggles).
        if numeric_id is not None and has_effective_module_access(user=user, tenant=tenant, module_key="bank"):
            bank_expense = BankExpense.objects.filter(tenant=tenant, id=numeric_id).first()
            if bank_expense:
                rel = reverse("bank-expenses-detail", kwargs={"pk": bank_expense.id})
                url = request.build_absolute_uri(rel) if request else rel
                return {
                    "module": "bank",
                    "expense_type": "bank",
                    "id": bank_expense.id,
                    "url": url,
                }

        # Fallback: only return raw external id (frontend can decide how to render).
        return {"module": "external", "expense_type": "unknown", "id": obj.expense_id, "url": None}

