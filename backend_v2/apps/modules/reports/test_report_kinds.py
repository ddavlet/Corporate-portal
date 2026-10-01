from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.modules.reports.report_kinds import (
    REPORT_KINDS,
    CashflowReportKind,
    PnlReportKind,
    UnknownReport,
    get_report_kind,
)
from apps.modules.reports.report_rules import ReportSettingsInvalid


class ReportKindsTests(SimpleTestCase):
    """Each report names its own source, rules and n8n endpoint; callers never branch on the report name."""

    def test_each_report_names_its_own_source_rules_and_endpoint(self):
        self.assertEqual(
            {key: (kind.n8n_endpoint, kind.source_field, kind.rules_field) for key, kind in REPORT_KINDS.items()},
            {
                "pnl": ("/n8n/pnl-data", "pnl_source", "pnl_config"),
                "cashflow": ("/n8n/cashflow-data", "cashflow_source", "cashflow_config"),
            },
        )

    def test_unknown_report(self):
        with self.assertRaises(UnknownReport):
            get_report_kind("ghost")

    def test_reads_only_its_own_fields(self):
        row = SimpleNamespace(pnl_source="backend", pnl_config={"a": 1}, cashflow_source=" N8N ", cashflow_config=None)
        self.assertEqual((PnlReportKind().source_of(row), PnlReportKind().rules_of(row)), ("backend", {"a": 1}))
        self.assertEqual((CashflowReportKind().source_of(row), CashflowReportKind().rules_of(row)), ("n8n", {}))

    def test_rules_are_validated_the_same_way_for_every_report(self):
        for kind in REPORT_KINDS.values():
            with self.assertRaises(ReportSettingsInvalid):
                kind.validate_rules({})

    @patch("apps.modules.reports.cashflow_builder.build_cashflow_payload_from_db", return_value={"revenue": []})
    def test_cashflow_is_built_by_its_own_builder(self, build):
        tenant = SimpleNamespace(id=1)
        self.assertEqual(get_report_kind("cashflow").build_payload(tenant=tenant, query_params={}), {"revenue": []})
        build.assert_called_once_with(tenant=tenant, query_params={})

    @patch("apps.modules.reports.pnl_builder.compute_unassigned_payment_purposes", return_value=[])
    def test_diagnostics_use_the_rules_they_are_given(self, compute):
        get_report_kind("pnl").unassigned_purposes(tenant_id=5, rules={"x": 1})
        compute.assert_called_once_with(tenant_id=5, cfg={"x": 1})
