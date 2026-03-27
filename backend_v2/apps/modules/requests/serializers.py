from rest_framework import serializers
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.db import connection

from apps.modules.requests.models import Approval, Request
from apps.modules.cashier.models import CashExpense
from apps.modules.bank_expenses.models import BankExpense
from apps.tenants.permissions import has_effective_module_access
from apps.tenants.models import TenantMembership, TenantUserRole

User = get_user_model()


class PortalRequestSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)
    expense_link = serializers.SerializerMethodField()
    requester = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), allow_null=True)
    requester_username = serializers.SerializerMethodField()

    class Meta:
        model = Request
        fields = [
            "id",
            "created_at",
            "created_by",
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
            "requester_username",
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
        read_only_fields = ["expense_link", "created_at", "created_by"]

    def validate(self, attrs):
        request_obj = self.context.get("request")
        tenant = getattr(request_obj, "tenant", None)

        requester = attrs.get("requester")
        if requester is None and self.instance is not None:
            requester = self.instance.requester

        if requester is None:
            raise serializers.ValidationError({"requester": "Requester is required."})

        has_membership = TenantMembership.objects.filter(
            tenant=tenant, user=requester, is_active=True
        ).exists()
        if not has_membership:
            raise serializers.ValidationError(
                {"requester": "Requester must be an active member of this tenant."}
            )

        has_requester_role = TenantUserRole.objects.filter(
            tenant=tenant, user=requester, role=TenantUserRole.ROLE_REQUESTER
        ).exists()
        if not has_requester_role:
            raise serializers.ValidationError(
                {"requester": "Requester must have role 'requester' in this tenant."}
            )

        return attrs

    def get_requester_username(self, obj):
        return obj.requester.username if obj.requester else None

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


class ApprovalSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)
    approver_username = serializers.SerializerMethodField()

    class Meta:
        model = Approval
        fields = [
            "id",
            "step",
            "step_type",
            "decision",
            "comment",
            "decided_at",
            "approver_user",
            "approver_username",
            "approver_tg_id",
            "message_id",
            "message_sent",
        ]
        read_only_fields = ["approver_username"]

    def get_approver_username(self, obj):
        return getattr(obj.approver_user, "username", None)


class PortalRequestDetailSerializer(PortalRequestSerializer):
    approvals = serializers.SerializerMethodField()

    class Meta(PortalRequestSerializer.Meta):
        fields = PortalRequestSerializer.Meta.fields + ["approvals"]

    def get_approvals(self, obj):
        # Some environments may not have applied approvals-table migration yet.
        if Approval._meta.db_table not in connection.introspection.table_names():
            return []
        queryset = Approval.objects.filter(request=obj).select_related("approver_user").order_by("step", "id")
        return ApprovalSerializer(queryset, many=True).data

