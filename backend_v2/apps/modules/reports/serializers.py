from __future__ import annotations

from datetime import date

from rest_framework import serializers

from apps.modules.reports.periods import (
    COMPARE_NONE,
    COMPARE_YOY,
    GRANULARITY_MONTH,
    GRANULARITY_QUARTER,
    PERIOD_LTM,
    PERIOD_MONTH,
    PERIOD_YEAR,
    PERIOD_YTD,
    PeriodSpec,
    month_key,
)
from apps.modules.reports.report_templates import TemplateSettingsInvalid, validate_template_settings
from apps.modules.reports.units import UNITS

REPORT_CHOICES = ("pnl", "cashflow")


class StatementQuerySerializer(serializers.Serializer):
    template = serializers.CharField(max_length=32)
    report = serializers.ChoiceField(choices=REPORT_CHOICES)
    period = serializers.ChoiceField(choices=(PERIOD_MONTH, PERIOD_YTD, PERIOD_YEAR, PERIOD_LTM), default=PERIOD_YTD)
    year = serializers.IntegerField(required=False, min_value=2000, max_value=2100)
    month = serializers.RegexField(r"^\d{4}-(0[1-9]|1[0-2])$", required=False)
    granularity = serializers.ChoiceField(
        choices=(GRANULARITY_MONTH, GRANULARITY_QUARTER), default=GRANULARITY_MONTH
    )
    compare = serializers.ChoiceField(choices=(COMPARE_NONE, COMPARE_YOY), default=COMPARE_NONE)
    refresh = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        today: date = self.context["today"]
        if attrs["period"] == PERIOD_YEAR:
            year = attrs.get("year")
            if year is None:
                raise serializers.ValidationError({"year": "Укажите год."})
            if year > today.year:
                raise serializers.ValidationError({"year": "Год ещё не наступил."})
        if attrs["period"] == PERIOD_MONTH:
            month = attrs.get("month")
            if not month:
                raise serializers.ValidationError({"month": "Укажите месяц в формате ГГГГ-ММ."})
            if month > month_key(today):
                raise serializers.ValidationError({"month": "Месяц ещё не наступил."})
            if int(month[:4]) < 2000:
                raise serializers.ValidationError({"month": "Месяц вне допустимого диапазона (с 2000 года)."})
        return attrs

    def period_spec(self) -> PeriodSpec:
        data = self.validated_data
        return PeriodSpec(
            kind=data["period"],
            year=data.get("year"),
            month=data.get("month"),
            granularity=data["granularity"],
            compare=data["compare"],
        )


class StatementExportQuerySerializer(StatementQuerySerializer):
    """`statement/` parameters plus the units the workbook's number formats use."""

    units = serializers.ChoiceField(choices=UNITS, default="m")


class StatementLinesQuerySerializer(serializers.Serializer):
    template = serializers.CharField(max_length=32)
    report = serializers.ChoiceField(choices=REPORT_CHOICES)
    line = serializers.RegexField(
        r"^[a-z_]+(\.[a-z0-9_]+)*$", max_length=120, required=False, allow_blank=True, default=""
    )
    source = serializers.ChoiceField(
        choices=("bank", "cash", "request", "invest_return", "unknown"), required=False, allow_blank=True, default=""
    )
    date_from = serializers.DateField()
    date_to = serializers.DateField()
    q = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")
    page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=200, default=50)

    def validate(self, attrs):
        if attrs["date_from"] > attrs["date_to"]:
            raise serializers.ValidationError({"date_from": "Начало периода позже конца."})
        return attrs


class ReportTemplateSettingsSerializer(serializers.Serializer):
    default_template = serializers.CharField(max_length=32)
    allowed_templates = serializers.ListField(child=serializers.CharField(max_length=32), allow_empty=True)

    def validate(self, attrs):
        try:
            default, allowed = validate_template_settings(attrs["default_template"], attrs["allowed_templates"])
        except TemplateSettingsInvalid as exc:
            raise serializers.ValidationError({"allowed_templates": str(exc)}) from exc
        return {"default_template": default, "allowed_templates": allowed}
