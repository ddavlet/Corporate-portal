from collections.abc import Mapping

from django.conf import settings
from rest_framework import serializers


def reject_client_pk_on_create(serializer: serializers.BaseSerializer) -> None:
    """Raise ValidationError if POST create body contains ``id`` (public API must not accept client PK)."""
    request = serializer.context.get("request")
    if not request or request.method != "POST" or serializer.instance is not None:
        return
    path = request.path or ""
    prefixes = getattr(settings, "N8N_INTEGRATION_URL_PREFIXES", None) or frozenset()
    if not prefixes:
        single = (getattr(settings, "N8N_INTEGRATION_URL_PREFIX", None) or "").rstrip("/")
        prefixes = frozenset({single}) if single else frozenset()
    if any(p and (path == p or path.startswith(p + "/")) for p in prefixes):
        return
    data = getattr(serializer, "initial_data", None)
    if isinstance(data, Mapping) and "id" in data:
        raise serializers.ValidationError({"id": "Client-supplied id is not allowed on create."})
