"""MCP tools for the Clients debt (дебиторка клиентов) module."""

from __future__ import annotations

from typing import Any

from apps.mcp_server.auth import require_module_access
from apps.mcp_server.utils import json_safe, validate_date

MODULE = "clients_debt"
_MAX_LIMIT = 500


def get_client_debts(
    tenant_id: int,
    doc_type: str = "",
    client_search: str = "",
    as_of: str = "",
    limit: int = 200,
) -> dict[str, Any]:
    """Return client debts from the latest snapshot of each doc_type.

    Debts are imported as dated snapshots; only the latest one (on or before `as_of`,
    default today) reflects the debt at that moment, so older snapshots are never summed.

    Filters (all optional):
    - doc_type: only this snapshot type
    - client_search: substring of client name or client id
    - as_of: use snapshots taken on or before this date (YYYY-MM-DD)
    - limit: max client rows (default 200, max 500), largest debt first
    """
    _, tenant = require_module_access(tenant_id, MODULE)
    validate_date(as_of, "as_of")

    from django.db.models import Count, Max, Q, Sum

    from apps.modules.clients_debt.models import ClientDebtSnapshot

    base = ClientDebtSnapshot.objects.filter(tenant=tenant)
    if doc_type:
        base = base.filter(doc_type=doc_type)
    if as_of:
        base = base.filter(snapshot_at__date__lte=as_of)

    latest = list(base.values("doc_type").annotate(snapshot_at=Max("snapshot_at")).order_by("doc_type"))
    if not latest:
        return {"snapshots": [], "clients": [], "clients_total": 0}

    in_latest = Q()
    for s in latest:
        in_latest |= Q(doc_type=s["doc_type"], snapshot_at=s["snapshot_at"])
    current = base.filter(in_latest)

    snapshots = [
        {
            "doc_type": s["doc_type"],
            "snapshot_at": s["snapshot_at"],
            **current.filter(doc_type=s["doc_type"], snapshot_at=s["snapshot_at"]).aggregate(
                clients_count=Count("id"), total_debt=Sum("debt_sum")
            ),
        }
        for s in latest
    ]

    if client_search:
        t = client_search.strip()
        current = current.filter(Q(client__icontains=t) | Q(client_id__icontains=t))

    limit = min(max(1, int(limit)), _MAX_LIMIT)
    clients_total = current.count()
    clients = list(
        current.order_by("-debt_sum", "client").values(
            "doc_type", "snapshot_at", "organization", "client", "client_id",
            "debt_sum", "quantity", "cert_discount",
        )[:limit]
    )
    return json_safe({"snapshots": snapshots, "clients": clients, "clients_total": clients_total})
