from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from rest_framework import serializers

from apps.modules.investments.billing_month_rules import month_first_day
from apps.modules.investments.funding import get_enabled_funding_config, is_module_enabled
from apps.modules.investments.funding_pool import request_kind
from apps.modules.requests.models import Request
from apps.modules.wallets.models import Wallet
from apps.modules.investments.models import (
    InvestCompany,
    InvestmentApprovalConfig,
    InvestmentApprovalConfigStep,
    InvestmentApprovalConfigStepApprover,
    InvestmentFormConfig,
    InvestmentFundingConfig,
    InvestmentProjectApprovalConfig,
    InvestmentProjectApprovalConfigStep,
    InvestmentProjectApprovalConfigStepApprover,
    InvestmentReturnApproval,
    InvestNotificationConfig,
    InvestPayoutSchedule,
    InvestPayoutScheduleShareLink,
    InvestReturn,
    ProjectInvestment,
    ProjectInvestmentApproval,
)
from apps.modules.requests.serializers import _display_user_name
from apps.modules.investments.services import (
    CBU_ARCHIVE_EMPTY_MESSAGE,
    clamp_rate_date_to_cbu_availability,
    usd_uzs_equivalents_with_rate_date_for_read,
    usd_uzs_rate_on_or_before,
)
from apps.modules.serializers_guard import reject_client_pk_on_create


def _cbu_rate_memo(serializer) -> dict:
    """Общий на запрос словарь для курсов из архива ЦБ (context разделяют все строки списка)."""
    context = serializer.context
    if not isinstance(context, dict):
        return {}
    return context.setdefault("_cbu_rate_memo", {})


def _normalize_currency(attrs: dict, key: str = "currency") -> None:
    val = attrs.get(key)
    if val is not None:
        attrs[key] = str(val).strip().upper()


class _CompanyScopeMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company_field = self.fields.get("company")
        if company_field is None:
            return
        tenant = getattr(self.context.get("request"), "tenant", None)
        if tenant:
            company_field.queryset = InvestCompany.objects.filter(tenant=tenant)
        else:
            company_field.queryset = InvestCompany.objects.none()


def investment_form_clear_company_if_disabled(attrs, request) -> dict:
    """When tenant disabled companies in form settings, drop company FK on write."""
    tenant = getattr(request, "tenant", None)
    if not tenant:
        return attrs
    cfg = InvestmentFormConfig.objects.filter(tenant=tenant).first()
    if cfg and not cfg.uses_companies:
        attrs["company"] = None
    return attrs


class InvestReturnSerializer(_CompanyScopeMixin, serializers.ModelSerializer):
    """
    ``sum_usd``/``sum_uzs`` — не хранятся в БД, а считаются на лету из ``sum``/``currency``
    и курса ЦБ на дату выплаты (CbuExchangeRate — единая точка правды, см. investments.services).
    ``rate_date`` — дата курса, по которому посчитаны эквиваленты: если курс на дату выплаты ещё
    не загружен, берётся ближайший предыдущий и ``rate_date`` отличается от ``date``.
    """

    sum_usd = serializers.SerializerMethodField()
    sum_uzs = serializers.SerializerMethodField()
    rate_date = serializers.SerializerMethodField()

    class Meta:
        model = InvestReturn
        fields = [
            "id",
            "tenant",
            "company",
            "payout_schedule",
            "date",
            "billing_date",
            "sum",
            "sum_usd",
            "sum_uzs",
            "rate_date",
            "comment",
            "confirmed",
            "currency",
            "type",
            "recipient",
            "created_at",
            "last_edit_at",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "tenant",
            "payout_schedule",
            "created_at",
            "last_edit_at",
            "created_by",
        ]

    def _equivalents(self, obj) -> tuple[Decimal | None, Decimal | None, date | None]:
        cached = getattr(obj, "_usd_uzs_equivalents_cache", None)
        if cached is None:
            rate_date = clamp_rate_date_to_cbu_availability(requested=obj.date)
            cached = usd_uzs_equivalents_with_rate_date_for_read(
                sum_val=obj.sum, currency=obj.currency, rate_date=rate_date, memo=_cbu_rate_memo(self)
            )
            obj._usd_uzs_equivalents_cache = cached
        return cached

    def get_sum_usd(self, obj):
        return self._equivalents(obj)[0]

    def get_sum_uzs(self, obj):
        return self._equivalents(obj)[1]

    def get_rate_date(self, obj) -> str | None:
        used = self._equivalents(obj)[2]
        return used.isoformat() if used is not None else None

    @staticmethod
    def _require_cbu_archive(effective_date) -> None:
        """Суммы считаются по архиву курсов (без сети): пустой архив — понятная ошибка, не 500."""
        rate_date = clamp_rate_date_to_cbu_availability(requested=effective_date)
        if usd_uzs_rate_on_or_before(rate_date) is None:
            raise serializers.ValidationError({"detail": CBU_ARCHIVE_EMPTY_MESSAGE})

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        _normalize_currency(attrs)
        merged_currency = attrs.get("currency")
        if self.instance is not None:
            merged_currency = merged_currency or self.instance.currency
        else:
            merged_currency = merged_currency or "USD"
        merged_currency = str(merged_currency or "USD").strip().upper()
        if merged_currency not in ("USD", "UZS"):
            raise serializers.ValidationError({"currency": "Допустимы только USD и UZS."})

        merged_date = attrs.get("date")
        if merged_date is None and self.instance is not None:
            merged_date = self.instance.date

        billing_in_attrs = "billing_date" in attrs
        billing_explicit = attrs.get("billing_date") if billing_in_attrs else None

        if self.instance is None:
            if merged_date is None:
                raise serializers.ValidationError({"date": "Укажите дату выплаты."})
            billing_source = billing_explicit if billing_explicit is not None else merged_date
            attrs["billing_date"] = month_first_day(billing_source)
        elif billing_in_attrs:
            if billing_explicit is None:
                raise serializers.ValidationError({"billing_date": "Укажите месяц назначения."})
            attrs["billing_date"] = month_first_day(billing_explicit)

        tenant = getattr(self.context.get("request"), "tenant", None)
        if tenant:
            cfg = InvestmentFormConfig.objects.filter(tenant=tenant).first()
            if cfg:
                allowed = cfg.allowed_return_types or []
                if allowed:
                    merged_type = attrs.get("type")
                    if merged_type is None and self.instance is not None:
                        merged_type = self.instance.type
                    if merged_type not in allowed:
                        raise serializers.ValidationError(
                            {"type": "Этот тип выплат отключён в настройках формы инвестиций."}
                        )
        return investment_form_clear_company_if_disabled(attrs, self.context.get("request"))

    def create(self, validated_data):
        self._require_cbu_archive(validated_data["date"])
        validated_data["sum"] = Decimal(str(validated_data["sum"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if "sum" in validated_data or "currency" in validated_data:
            self._require_cbu_archive(validated_data.get("date", instance.date))
            if "sum" in validated_data:
                validated_data["sum"] = Decimal(str(validated_data["sum"])).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
        return super().update(instance, validated_data)


class InvestPayoutScheduleSerializer(_CompanyScopeMixin, serializers.ModelSerializer):
    remaining_amount = serializers.SerializerMethodField()

    class Meta:
        model = InvestPayoutSchedule
        fields = [
            "id",
            "tenant",
            "company",
            "payout_date",
            "amount",
            "currency",
            "is_paid",
            "closed_manually",
            "payment_amount",
            "remaining_amount",
            "comment",
            "return_type",
            "recipient",
            "created_return",
            "created_at",
            "last_edit_at",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "tenant",
            "closed_manually",
            "created_return",
            "created_at",
            "last_edit_at",
            "created_by",
        ]

    def get_remaining_amount(self, obj) -> str:
        """Outstanding amount still owed (amount - already-paid), clamped at zero."""
        remaining = Decimal(str(obj.amount or 0)) - Decimal(str(obj.payment_amount or 0))
        if remaining < 0:
            remaining = Decimal("0")
        return str(remaining.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        _normalize_currency(attrs)
        # Editing is_paid directly (admin form) is treated as a manual open/close decision so
        # the soft-coupling recompute respects it: closing keeps the schedule closed even when
        # under-paid; reopening lets the amount-based auto-status take over again.
        if "is_paid" in attrs:
            attrs["closed_manually"] = bool(attrs["is_paid"])
        return investment_form_clear_company_if_disabled(attrs, self.context.get("request"))


class ProjectInvestmentSerializer(_CompanyScopeMixin, serializers.ModelSerializer):
    # Заявки на расход — основания вложения (инвестиционный режим), только для чтения.
    source_requests = serializers.SerializerMethodField()

    class Meta:
        model = ProjectInvestment
        fields = [
            "id",
            "tenant",
            "company",
            "date",
            "amount",
            "currency",
            "funding_method",
            "comment",
            "confirmed",
            "created_at",
            "last_edit_at",
            "created_by",
            "source_requests",
        ]
        read_only_fields = ["id", "tenant", "confirmed", "created_at", "last_edit_at", "created_by"]

    # Поля вложения, собранного по заявкам: выведены из заявок и не редактируются.
    COLLECTED_LOCKED_FIELDS = ("amount", "currency", "funding_method")

    # Обязателен при создании; импорт из n8n (подкласс) отключает требование.
    funding_method_required_on_create = True

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        _normalize_currency(attrs)
        if self.instance is None and self.funding_method_required_on_create and not attrs.get("funding_method"):
            raise serializers.ValidationError({"funding_method": "Укажите способ внесения."})
        self._validate_collected_fields_locked(attrs)
        self._validate_cash_currency(attrs)
        return investment_form_clear_company_if_disabled(attrs, self.context.get("request"))

    def get_source_requests(self, obj):
        if not obj.pk:
            return []
        if "request_links" in getattr(obj, "_prefetched_objects_cache", {}):
            links = obj.request_links.all()
        else:
            links = obj.request_links.select_related("request")
        return [
            {
                "id": link.request.id,
                "amount": str(link.request.amount),
                "currency": link.request.currency,
                "payment_type": link.request.payment_type,
            }
            for link in links
        ]

    def _validate_collected_fields_locked(self, attrs):
        if self.instance is None:
            return
        changed = [
            field
            for field in self.COLLECTED_LOCKED_FIELDS
            if field in attrs and attrs[field] != getattr(self.instance, field)
        ]
        if not changed or not self.instance.request_links.exists():
            return
        raise serializers.ValidationError(
            {
                field: "Вложение собрано по заявкам: сумма, валюта и способ внесения не меняются."
                for field in changed
            }
        )

    def _validate_cash_currency(self, attrs):
        if "funding_method" not in attrs and "currency" not in attrs:
            return
        tenant = getattr(self.context.get("request"), "tenant", None)
        method = attrs.get("funding_method") or (self.instance.funding_method if self.instance else None)
        if tenant is None or method != ProjectInvestment.FundingMethod.CASH:
            return
        cfg = get_enabled_funding_config(tenant)
        if cfg is None or cfg.cash_wallet is None:
            return
        currency = attrs.get("currency") or (self.instance.currency if self.instance else None)
        if currency and currency != cfg.cash_wallet.currency:
            raise serializers.ValidationError(
                {"currency": f"Валюта вложения должна совпадать с валютой инвестиционной кассы ({cfg.cash_wallet.currency})."}
            )


class ProjectInvestmentWithEquivalentsSerializer(ProjectInvestmentSerializer):
    """
    Заявка на вложение + ``sum_usd``/``sum_uzs`` — эквиваленты ``amount`` по курсу ЦБ на дату заявки
    (как у InvestReturnSerializer), чтобы UI мог показать общий итог без деления по валютам.
    Для валют кроме USD/UZS (EUR) кросс-курса в архиве нет — эквиваленты ``None``.
    ``rate_date`` — дата курса ЦБ, по которому посчитаны эквиваленты (None — эквивалентов нет);
    отличается от ``date``, если курс на дату ещё не загружен и взят ближайший предыдущий.
    """

    sum_usd = serializers.SerializerMethodField()
    sum_uzs = serializers.SerializerMethodField()
    rate_date = serializers.SerializerMethodField()

    class Meta(ProjectInvestmentSerializer.Meta):
        fields = ProjectInvestmentSerializer.Meta.fields + ["sum_usd", "sum_uzs", "rate_date"]

    def _equivalents(self, obj) -> tuple[Decimal | None, Decimal | None, date | None]:
        cached = getattr(obj, "_usd_uzs_equivalents_cache", None)
        if cached is None:
            if str(obj.currency or "").strip().upper() in ("USD", "UZS"):
                rate_date = clamp_rate_date_to_cbu_availability(requested=obj.date)
                cached = usd_uzs_equivalents_with_rate_date_for_read(
                    sum_val=obj.amount, currency=obj.currency, rate_date=rate_date, memo=_cbu_rate_memo(self)
                )
            else:
                cached = (None, None, None)
            obj._usd_uzs_equivalents_cache = cached
        return cached

    def get_sum_usd(self, obj):
        return self._equivalents(obj)[0]

    def get_sum_uzs(self, obj):
        return self._equivalents(obj)[1]

    def get_rate_date(self, obj) -> str | None:
        used = self._equivalents(obj)[2]
        return used.isoformat() if used is not None else None


class FundingPoolRequestSerializer(serializers.ModelSerializer):
    """Заявка в пуле «Вложение по заявкам»."""

    kind = serializers.SerializerMethodField()
    is_payed = serializers.SerializerMethodField()

    class Meta:
        model = Request
        fields = [
            "id",
            "submitted_at",
            "kind",
            "payment_type",
            "payment_purpose",
            "description",
            "amount",
            "currency",
            "status",
            "is_payed",
        ]
        read_only_fields = fields

    def get_kind(self, obj) -> str:
        return request_kind(obj)

    def get_is_payed(self, obj) -> bool:
        return obj.status == Request.STATUS_PAYED


class FundingCollectPayloadSerializer(_CompanyScopeMixin, serializers.Serializer):
    funding_method = serializers.ChoiceField(choices=ProjectInvestment.FundingMethod.choices)
    request_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False)
    comment = serializers.CharField(required=False, allow_blank=True, default="")
    company = serializers.PrimaryKeyRelatedField(
        queryset=InvestCompany.objects.none(), required=False, allow_null=True, default=None
    )

    def validate(self, attrs):
        tenant = getattr(self.context.get("request"), "tenant", None)
        cfg = InvestmentFormConfig.objects.filter(tenant=tenant).first() if tenant else None
        uses_companies = cfg.uses_companies if cfg else True
        if not uses_companies:
            attrs["company"] = None
        elif attrs.get("company") is None:
            raise serializers.ValidationError({"company": "Укажите компанию."})
        return attrs


class InvestCompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = InvestCompany
        fields = [
            "id",
            "tenant",
            "name",
            "comment",
            "is_active",
            "created_at",
            "last_edit_at",
            "created_by",
        ]
        read_only_fields = ["id", "tenant", "created_at", "last_edit_at", "created_by"]

    def validate_name(self, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise serializers.ValidationError("Name cannot be empty.")
        return normalized

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        return attrs


class InvestPayoutScheduleShareLinkSerializer(_CompanyScopeMixin, serializers.ModelSerializer):
    class Meta:
        model = InvestPayoutScheduleShareLink
        fields = [
            "id",
            "tenant",
            "token",
            "company",
            "paid_filter",
            "is_active",
            "created_at",
            "created_by",
        ]
        read_only_fields = ["id", "tenant", "token", "is_active", "created_at", "created_by"]

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        return investment_form_clear_company_if_disabled(attrs, self.context.get("request"))


class PublicInvestPayoutScheduleShareViewSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    payout_date = serializers.DateField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    is_paid = serializers.BooleanField()
    payment_amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    comment = serializers.CharField(allow_blank=True)
    company = serializers.IntegerField(allow_null=True)
    company_name = serializers.CharField(allow_blank=True)
    currency = serializers.CharField()


class InvestmentApprovalConfigStepSerializer(serializers.Serializer):
    step = serializers.IntegerField(min_value=1)
    step_type = serializers.ChoiceField(
        choices=InvestmentApprovalConfigStep.STEP_TYPE_CHOICES,
        default=InvestmentApprovalConfigStep.STEP_TYPE_SERIAL,
    )
    is_enabled = serializers.BooleanField(default=True)
    telegram_chat_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    approver_user_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=True,
        required=False,
    )


class InvestNotificationConfigSerializer(serializers.Serializer):
    responsible_user_id = serializers.IntegerField(min_value=1)
    days_before = serializers.IntegerField(min_value=1, max_value=365)
    overdue_notify_every_days = serializers.IntegerField(min_value=0, max_value=365)
    notify_hour = serializers.IntegerField(min_value=0, max_value=23)
    is_active = serializers.BooleanField()
    telegram_chat_id = serializers.IntegerField(required=False, allow_null=True, default=None)


class InvestmentFormConfigSerializer(serializers.Serializer):
    uses_companies = serializers.BooleanField()
    allowed_return_types = serializers.ListField(
        child=serializers.ChoiceField(choices=InvestReturn.ReturnType.choices),
        allow_empty=False,
    )


class InvestmentFundingConfigSerializer(serializers.Serializer):
    """Вход PUT /funding-config/. Проверки принадлежности кошельков — в validate (нужен tenant)."""

    is_enabled = serializers.BooleanField()
    cash_wallet_id = serializers.IntegerField(required=False, allow_null=True)
    bank_wallet_id = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
        tenant = self.context["tenant"]
        enabled = attrs["is_enabled"]
        resolved = {}
        stored = InvestmentFundingConfig.objects.filter(tenant=tenant).first()
        for key, wallet_type, label in (
            ("cash_wallet_id", Wallet.Type.CASH, "Инвестиционная касса"),
            ("bank_wallet_id", Wallet.Type.BANK, "Инвестиционный счёт"),
        ):
            wallet = None
            if key not in attrs:
                # Ключ не передан — сохраняем текущее значение; очищает только явный null.
                if stored is not None:
                    wallet = stored.cash_wallet if key == "cash_wallet_id" else stored.bank_wallet
                resolved[key] = wallet
                continue
            wallet_id = attrs[key]
            if wallet_id is not None:
                wallet = Wallet.objects.filter(pk=wallet_id, tenant=tenant, wallet_type=wallet_type).first()
                if wallet is None:
                    raise serializers.ValidationError({key: f"{label}: кошелёк не найден или неверного типа."})
            resolved[key] = wallet
        if enabled:
            if resolved["cash_wallet_id"] is None:
                raise serializers.ValidationError({"cash_wallet_id": "Выберите инвестиционную кассу."})
            if resolved["bank_wallet_id"] is None and is_module_enabled(tenant, "bank"):
                raise serializers.ValidationError({"bank_wallet_id": "Выберите инвестиционный счёт."})
        attrs["cash_wallet"] = resolved["cash_wallet_id"]
        attrs["bank_wallet"] = resolved["bank_wallet_id"]
        return attrs


class InvestmentApprovalConfigSerializer(serializers.Serializer):
    return_type = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=25)
    recipient = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=20)
    is_enabled = serializers.BooleanField(default=False)
    steps = InvestmentApprovalConfigStepSerializer(many=True)
    approver_candidates = serializers.ListField(read_only=True)

    def validate_return_type(self, value):
        if value in (None, ""):
            return None
        valid = {c[0] for c in InvestReturn.ReturnType.choices}
        if value not in valid:
            raise serializers.ValidationError("Недопустимый тип выплаты.")
        return value

    def validate_recipient(self, value):
        if value in (None, ""):
            return None
        valid = {c[0] for c in InvestReturn.Recipient.choices}
        if value not in valid:
            raise serializers.ValidationError("Недопустимый получатель.")
        return value

    def validate_steps(self, value):
        raw_steps = (getattr(self, "initial_data", None) or {}).get("steps")
        raw_by_step: dict[int, dict] = {}
        if isinstance(raw_steps, list):
            for r in raw_steps:
                if isinstance(r, dict) and "step" in r:
                    try:
                        raw_by_step[int(r["step"])] = r
                    except (TypeError, ValueError):
                        continue
        seen_steps: set[int] = set()
        for row in value:
            step = int(row["step"])
            if step in seen_steps:
                raise serializers.ValidationError("Step numbers must be unique.")
            seen_steps.add(step)
            raw = raw_by_step.get(step, {})
            # После вложенного сериализатора step_type иногда не попадает в row — берём из initial_data.
            step_type = (
                row.get("step_type")
                or raw.get("step_type")
                or InvestmentApprovalConfigStep.STEP_TYPE_SERIAL
            )
            is_enabled = row.get("is_enabled", True)
            approver_ids = row.get("approver_user_ids") or raw.get("approver_user_ids") or []
            if is_enabled:
                if step_type != InvestmentApprovalConfigStep.STEP_TYPE_NOTIFICATION and not approver_ids:
                    raise serializers.ValidationError("У активного этапа должен быть хотя бы один согласующий.")
                if step_type in (
                    InvestmentApprovalConfigStep.STEP_TYPE_CONFIRMATION,
                    InvestmentApprovalConfigStep.STEP_TYPE_NOTIFICATION,
                ):
                    chat_id = row.get("telegram_chat_id")
                    if chat_id in (None, ""):
                        chat_id = raw.get("telegram_chat_id")
                    if chat_id in (None, ""):
                        raise serializers.ValidationError(
                            "Для этапов confirmation и notification нужен telegram_chat_id (Telegram чат)."
                        )
                    row["telegram_chat_id"] = chat_id
            row["step_type"] = step_type
            if step_type == InvestmentApprovalConfigStep.STEP_TYPE_SERIAL:
                row["telegram_chat_id"] = None
        return value


class InvestmentApprovalDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=[InvestmentReturnApproval.DECISION_APPROVED, InvestmentReturnApproval.DECISION_REJECTED]
    )
    approver_recipient_id = serializers.IntegerField(required=False)
    approver_external_user_id = serializers.IntegerField(required=False)
    comment = serializers.CharField(required=False, allow_blank=True)


class InvestmentProjectApprovalConfigSerializer(serializers.Serializer):
    is_enabled = serializers.BooleanField(default=False)
    steps = InvestmentApprovalConfigStepSerializer(many=True)

    def validate_steps(self, value):
        raw_steps = (getattr(self, "initial_data", None) or {}).get("steps")
        raw_by_step: dict[int, dict] = {}
        if isinstance(raw_steps, list):
            for r in raw_steps:
                if isinstance(r, dict) and "step" in r:
                    try:
                        raw_by_step[int(r["step"])] = r
                    except (TypeError, ValueError):
                        continue
        seen_steps: set[int] = set()
        for row in value:
            step = int(row["step"])
            if step in seen_steps:
                raise serializers.ValidationError("Step numbers must be unique.")
            seen_steps.add(step)
            raw = raw_by_step.get(step, {})
            step_type = (
                row.get("step_type")
                or raw.get("step_type")
                or InvestmentProjectApprovalConfigStep.STEP_TYPE_SERIAL
            )
            is_enabled = row.get("is_enabled", True)
            approver_ids = row.get("approver_user_ids") or raw.get("approver_user_ids") or []
            if is_enabled:
                if step_type != InvestmentProjectApprovalConfigStep.STEP_TYPE_NOTIFICATION and not approver_ids:
                    raise serializers.ValidationError("У активного этапа должен быть хотя бы один согласующий.")
                if step_type in (
                    InvestmentProjectApprovalConfigStep.STEP_TYPE_CONFIRMATION,
                    InvestmentProjectApprovalConfigStep.STEP_TYPE_NOTIFICATION,
                ):
                    chat_id = row.get("telegram_chat_id")
                    if chat_id in (None, ""):
                        chat_id = raw.get("telegram_chat_id")
                    if chat_id in (None, ""):
                        raise serializers.ValidationError(
                            "Для этапов confirmation и notification нужен telegram_chat_id (Telegram чат)."
                        )
                    row["telegram_chat_id"] = chat_id
            row["step_type"] = step_type
            if step_type == InvestmentProjectApprovalConfigStep.STEP_TYPE_SERIAL:
                row["telegram_chat_id"] = None
        return value


class InvestmentApprovalWebhookSerializer(serializers.Serializer):
    event = serializers.CharField()
    payload = serializers.CharField()
    user_id = serializers.CharField()
    recipient_id = serializers.CharField()
    message_id = serializers.IntegerField(required=False)
    platform = serializers.CharField(default="telegram")


# --- Read-only serializers for admin / module data inspection (list + retrieve only) ---


class InvestmentFormConfigReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvestmentFormConfig
        fields = ["id", "tenant", "uses_companies", "allowed_return_types", "created_at", "updated_at"]
        read_only_fields = fields


class InvestmentApprovalConfigReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvestmentApprovalConfig
        fields = ["id", "tenant", "return_type", "recipient", "is_enabled", "created_at", "updated_at"]
        read_only_fields = fields


class InvestmentApprovalConfigStepReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvestmentApprovalConfigStep
        fields = ["id", "config", "step", "step_type", "is_enabled", "telegram_chat_id"]
        read_only_fields = fields


class InvestmentApprovalConfigStepApproverReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvestmentApprovalConfigStepApprover
        fields = ["id", "step", "approver_user"]
        read_only_fields = fields


class InvestmentReturnApprovalReadSerializer(serializers.ModelSerializer):
    approver_username = serializers.SerializerMethodField()
    # Derived from the single source of truth (`telegram_message`); kept for API stability.
    gateway_message_id = serializers.ReadOnlyField()
    message_sent = serializers.ReadOnlyField()
    message_sent_at = serializers.ReadOnlyField()

    class Meta:
        model = InvestmentReturnApproval
        fields = [
            "id",
            "tenant",
            "invest_return",
            "step",
            "step_type",
            "approver_user",
            "approver_username",
            "approver_recipient_id",
            "approver_external_user_id",
            "decision",
            "decision_comment",
            "decided_at",
            "gateway_message_id",
            "message_sent",
            "message_sent_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_approver_username(self, obj):
        return _display_user_name(getattr(obj, "approver_user", None))


class InvestmentProjectApprovalConfigReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvestmentProjectApprovalConfig
        fields = ["id", "tenant", "is_enabled", "created_at", "updated_at"]
        read_only_fields = fields


class InvestmentProjectApprovalConfigStepReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvestmentProjectApprovalConfigStep
        fields = ["id", "config", "step", "step_type", "is_enabled", "payment_chat_id"]
        read_only_fields = fields


class InvestmentProjectApprovalConfigStepApproverReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvestmentProjectApprovalConfigStepApprover
        fields = ["id", "step", "approver_user"]
        read_only_fields = fields


class ProjectInvestmentApprovalReadSerializer(serializers.ModelSerializer):
    approver_username = serializers.SerializerMethodField()
    # Derived from the single source of truth (`telegram_message`); kept for API stability.
    gateway_message_id = serializers.ReadOnlyField()
    message_sent = serializers.ReadOnlyField()
    message_sent_at = serializers.ReadOnlyField()

    class Meta:
        model = ProjectInvestmentApproval
        fields = [
            "id",
            "tenant",
            "project_investment",
            "step",
            "step_type",
            "approver_user",
            "approver_username",
            "approver_recipient_id",
            "approver_external_user_id",
            "decision",
            "decision_comment",
            "decided_at",
            "gateway_message_id",
            "message_sent",
            "message_sent_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_approver_username(self, obj):
        return _display_user_name(getattr(obj, "approver_user", None))


class InvestReportConfigWriteSerializer(serializers.Serializer):
    is_active = serializers.BooleanField()
    telegram_chat_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    weekday = serializers.IntegerField(min_value=0, max_value=6)
    send_hour = serializers.IntegerField(min_value=0, max_value=23)
    target_annual_rate = serializers.DecimalField(
        max_digits=6, decimal_places=2, min_value=Decimal("0"), max_value=Decimal("1000"),
        required=False, allow_null=True, default=None,
    )
    start_month = serializers.IntegerField(min_value=1, max_value=12, required=False, allow_null=True, default=None)
    last_payouts_count = serializers.IntegerField(min_value=0, max_value=10)
    late_payment_day = serializers.IntegerField(min_value=1, max_value=31)

    def validate(self, attrs):
        from apps.modules.telegram_approvals.models import TenantTelegramChat

        tenant = self.context["tenant"]
        chat_id = attrs.get("telegram_chat_id")
        if chat_id is not None and not TenantTelegramChat.objects.filter(
            tenant=tenant, pk=chat_id, is_active=True
        ).exists():
            raise serializers.ValidationError({"telegram_chat_id": "Telegram-группа не найдена или отключена."})
        if attrs["is_active"] and chat_id is None:
            raise serializers.ValidationError({"telegram_chat_id": "Выберите Telegram-группу, чтобы включить отчёт."})
        return attrs


class InvestReportPreviewQuerySerializer(serializers.Serializer):
    """Preview query: date + unsaved calculation settings (empty value = clear the setting)."""

    date = serializers.DateField(required=False)
    target_annual_rate = serializers.DecimalField(
        max_digits=6, decimal_places=2, min_value=Decimal("0"), max_value=Decimal("1000"),
        required=False, allow_null=True,
    )
    start_month = serializers.IntegerField(min_value=1, max_value=12, required=False, allow_null=True)
    last_payouts_count = serializers.IntegerField(min_value=0, max_value=10, required=False)
    late_payment_day = serializers.IntegerField(min_value=1, max_value=31, required=False)

    def validate_date(self, value):
        from apps.modules.investments.services import tashkent_today

        if value > tashkent_today():
            raise serializers.ValidationError("Дата отчёта не может быть позже сегодняшней.")
        return value
