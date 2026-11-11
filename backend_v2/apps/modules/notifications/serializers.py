from rest_framework import serializers


class ActionItemSerializer(serializers.Serializer):
    kind = serializers.CharField()
    id = serializers.IntegerField()
    approval_id = serializers.IntegerField()
    step = serializers.IntegerField()
    step_type = serializers.CharField()
    title = serializers.CharField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField(allow_blank=True)
    type_code = serializers.CharField(allow_blank=True)
    type_label = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()
    link = serializers.CharField()


class ActionItemTenantSerializer(serializers.Serializer):
    subdomain = serializers.CharField()
    name = serializers.CharField()


class TenantActionItemSerializer(ActionItemSerializer):
    tenant = ActionItemTenantSerializer()
