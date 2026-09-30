"""One definition per report: where its data source and rules are stored and how it is built.

Every caller (the loader, the rules API, the statement warnings) looks a report up here instead of branching on
its name; a new report is a new ``ReportKind`` subclass and one entry in ``REPORT_KINDS``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from apps.modules.reports import cashflow_builder, pnl_builder
from apps.modules.reports.report_rules import validate_rules

# Values of TenantReportSettings.pnl_source / cashflow_source.
SOURCE_N8N = "n8n"
SOURCE_BACKEND = "backend"
REPORT_SOURCES = (SOURCE_N8N, SOURCE_BACKEND)


class UnknownReport(LookupError):
    """No report is registered under this key."""


class ReportKind(ABC):
    key: ClassVar[str]
    n8n_endpoint: ClassVar[str]
    source_field: ClassVar[str]
    rules_field: ClassVar[str]

    def source_of(self, row: Any) -> str:
        """This report's source in a TenantReportSettings row, normalised (``n8n`` / ``backend``)."""
        return str(getattr(row, self.source_field, "") or "").strip().lower()

    def rules_of(self, row: Any) -> dict[str, Any]:
        """This report's rules in a TenantReportSettings row; anything but a JSON object reads as no rules."""
        rules = getattr(row, self.rules_field, None)
        return rules if isinstance(rules, dict) else {}

    def validate_rules(self, rules: dict[str, Any]) -> None:
        validate_rules(rules)

    @abstractmethod
    def build_payload(self, *, tenant: Any, query_params: dict[str, Any]) -> dict[str, Any]:
        """Raw report blocks built from the database, in the shape of the n8n webhook."""

    @abstractmethod
    def unassigned_purposes(self, *, tenant_id: int, rules: dict[str, Any]) -> list[dict[str, Any]]:
        """Payment purposes of paid requests in this report's scope that no section takes."""


# The builders are looked up on their modules at call time, so tests can patch them there.
class PnlReportKind(ReportKind):
    key = "pnl"
    n8n_endpoint = "/n8n/pnl-data"
    source_field = "pnl_source"
    rules_field = "pnl_config"

    def build_payload(self, *, tenant: Any, query_params: dict[str, Any]) -> dict[str, Any]:
        return pnl_builder.build_pnl_payload_from_db(tenant=tenant, query_params=query_params)

    def unassigned_purposes(self, *, tenant_id: int, rules: dict[str, Any]) -> list[dict[str, Any]]:
        return pnl_builder.compute_unassigned_payment_purposes(tenant_id=tenant_id, cfg=rules)


class CashflowReportKind(ReportKind):
    key = "cashflow"
    n8n_endpoint = "/n8n/cashflow-data"
    source_field = "cashflow_source"
    rules_field = "cashflow_config"

    def build_payload(self, *, tenant: Any, query_params: dict[str, Any]) -> dict[str, Any]:
        return cashflow_builder.build_cashflow_payload_from_db(tenant=tenant, query_params=query_params)

    def unassigned_purposes(self, *, tenant_id: int, rules: dict[str, Any]) -> list[dict[str, Any]]:
        return cashflow_builder.compute_unassigned_payment_purposes_cashflow(tenant_id=tenant_id, cfg=rules)


REPORT_KINDS: dict[str, ReportKind] = {kind.key: kind for kind in (PnlReportKind(), CashflowReportKind())}


def get_report_kind(key: str) -> ReportKind:
    kind = REPORT_KINDS.get(key)
    if kind is None:
        raise UnknownReport(key)
    return kind
