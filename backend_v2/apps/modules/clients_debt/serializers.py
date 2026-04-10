from collections.abc import Mapping
from datetime import datetime

from django.utils import timezone
from rest_framework import serializers

from apps.modules.clients_debt.models import ClientDebtSnapshot
from apps.modules.serializers_guard import reject_client_pk_on_create


def _normalize_datetime_input(value):
    if value in (None, ""):
        return value
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if not raw:
            return value
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return value
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_default_timezone())
    return dt


class ClientDebtSnapshotSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

    class Meta:
        model = ClientDebtSnapshot
        fields = [
            "id",
            "snapshot_at",
            "doc_type",
            "organization",
            "client",
            "client_id",
            "debt_sum",
            "quantity",
            "cert_discount",
            "payload",
            "created_at",
            "created_by",
        ]
        read_only_fields = ["created_at", "created_by"]

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            mutable = dict(data)
            if "snapshot_at" not in mutable and "date" in mutable:
                mutable["snapshot_at"] = mutable.get("date")
            if "snapshot_at" in mutable:
                mutable["snapshot_at"] = _normalize_datetime_input(mutable.get("snapshot_at"))
            data = mutable
        return super().to_internal_value(data)

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        attrs = super().validate(attrs)
        if not attrs.get("snapshot_at") and self.instance is None:
            raise serializers.ValidationError({"snapshot_at": "This field is required."})
        return attrs

