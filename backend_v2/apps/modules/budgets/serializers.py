from decimal import Decimal

from django.utils import timezone

from django.db.models import Sum
from rest_framework import serializers

from apps.modules.budgets.models import Budget
from apps.modules.serializers_guard import reject_client_pk_on_create


def _period_date_range(period_type: str, year: int, period_index: int):
    """Return (start_date, end_date) for the given period. end_date is exclusive.

    period_index is always a month number (1-12) as sent by the frontend.
    For quarterly budgets it is mapped to the containing quarter internally.
    """
    from datetime import date
    if period_type == Budget.PERIOD_MONTHLY:
        month = max(1, min(12, period_index))
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    elif period_type == Budget.PERIOD_QUARTERLY:
        # Convert month (1-12) → quarter (1-4) so the frontend month selector works
        # for quarterly budgets without any special-casing on the client side.
        quarter = (max(1, min(12, period_index)) - 1) // 3 + 1
        start_month = (quarter - 1) * 3 + 1
        end_month = start_month + 3
        start = date(year, start_month, 1)
        end = date(year + 1, 1, 1) if end_month > 12 else date(year, end_month, 1)
    else:
        start = date(year, 1, 1)
        end = date(year + 1, 1, 1)
    return start, end


class BudgetSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    spent_amount = serializers.SerializerMethodField()
    remaining_amount = serializers.SerializerMethodField()
    utilization_pct = serializers.SerializerMethodField()

    class Meta:
        model = Budget
        fields = [
            "id",
            "tenant",
            "name",
            "category",
            "category_name",
            "period_type",
            "limit_amount",
            "currency",
            "is_active",
            "created_at",
            "created_by",
            "spent_amount",
            "remaining_amount",
            "utilization_pct",
        ]
        read_only_fields = [
            "id", "tenant", "created_at", "created_by",
            "category_name", "spent_amount", "remaining_amount", "utilization_pct",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Scope category queryset to the current tenant.
        request = self.context.get("request")
        tenant = getattr(request, "tenant", None) if request else None
        if tenant:
            from apps.modules.requests.models import RequestCategory
            self.fields["category"].queryset = RequestCategory.objects.filter(tenant=tenant)

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        request = self.context.get("request")
        tenant = getattr(request, "tenant", None) if request else None

        # Pre-validate unique name constraint to return 400 instead of IntegrityError.
        if tenant:
            name = attrs.get("name")
            if name is None and self.instance is not None:
                name = self.instance.name
            if name:
                qs = Budget.objects.filter(tenant=tenant, name=name)
                if self.instance is not None:
                    qs = qs.exclude(pk=self.instance.pk)
                if qs.exists():
                    raise serializers.ValidationError({"name": "Бюджет с таким названием уже существует."})
        return attrs

    def _get_period_context(self):
        ctx = self.context
        today = timezone.localdate()
        year = int(ctx.get("year") or today.year)
        period_index = int(ctx.get("period_index") or today.month)
        return year, period_index

    def _compute_spent(self, obj) -> Decimal:
        from apps.modules.requests.models import Request
        # Cache per budget pk to avoid 3 DB queries per row (one for each computed field).
        if not hasattr(self, "_spent_cache"):
            self._spent_cache: dict[int, Decimal] = {}
        if obj.pk not in self._spent_cache:
            year, period_index = self._get_period_context()
            start, end = _period_date_range(obj.period_type, year, period_index)
            # Use billing_date (DateField, always set) instead of created_at__date so the
            # query can use a plain btree index rather than a function-based scan.
            total = (
                Request.objects.filter(
                    tenant=obj.tenant,
                    category=obj.category.name,
                    currency=obj.currency,
                    status__in=[Request.STATUS_APPROVED, Request.STATUS_PAYED],
                    billing_date__gte=start,
                    billing_date__lt=end,
                    source_tenant__isnull=True,
                ).aggregate(total=Sum("amount"))["total"]
            )
            self._spent_cache[obj.pk] = total or Decimal("0")
        return self._spent_cache[obj.pk]

    def get_spent_amount(self, obj):
        return str(self._compute_spent(obj))

    def get_remaining_amount(self, obj):
        return str(obj.limit_amount - self._compute_spent(obj))

    def get_utilization_pct(self, obj):
        if not obj.limit_amount:
            return 0
        return round(float(self._compute_spent(obj) / obj.limit_amount * 100), 1)
