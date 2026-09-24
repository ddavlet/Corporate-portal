from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.modules.reports.layouts import BalanceSpec, ProfessionalCashflowLayout, RatioSpec, ResultSpec
from apps.modules.reports.report_templates import (
    REPORT_TEMPLATES,
    TemplateNotFound,
    TemplateNotStatement,
    TemplateSettingsInvalid,
    resolve_statement_layout,
    tenant_template_settings,
    validate_template_settings,
)


class ValidateTemplateSettingsTests(SimpleTestCase):
    def test_normalizes_and_accepts(self):
        self.assertEqual(
            validate_template_settings(" professional ", ["professional", " classic", "professional"]),
            ("professional", ["professional", "classic"]),
        )

    def test_rejects_empty_unknown_and_default_outside_allowed(self):
        with self.assertRaises(TemplateSettingsInvalid):
            validate_template_settings("classic", [])
        with self.assertRaises(TemplateSettingsInvalid):
            validate_template_settings("classic", ["classic", "ghost"])
        with self.assertRaises(TemplateSettingsInvalid):
            validate_template_settings("professional", ["classic"])


class TenantTemplateSettingsTests(SimpleTestCase):
    def test_missing_row_means_classic_with_both_allowed(self):
        self.assertEqual(tenant_template_settings(None), ("classic", ["classic", "professional"]))

    def test_unknown_keys_are_dropped(self):
        row = SimpleNamespace(default_template="ghost", allowed_templates=["professional", "ghost"])
        self.assertEqual(tenant_template_settings(row), ("professional", ["professional"]))

    def test_empty_allowed_falls_back_to_classic(self):
        row = SimpleNamespace(default_template="professional", allowed_templates=[])
        self.assertEqual(tenant_template_settings(row), ("classic", ["classic"]))


class ResolveStatementLayoutTests(SimpleTestCase):
    def test_professional_layouts(self):
        self.assertIsInstance(resolve_statement_layout("professional", "cashflow"), ProfessionalCashflowLayout)

    def test_classic_and_unknown_are_rejected(self):
        with self.assertRaises(TemplateNotStatement):
            resolve_statement_layout("classic", "pnl")
        with self.assertRaises(TemplateNotFound):
            resolve_statement_layout("ghost", "pnl")


class RegisteredLayoutConsistencyTests(SimpleTestCase):
    def test_every_registered_layout_references_known_rows(self):
        for template in REPORT_TEMPLATES.values():
            for report, layout_cls in template.layouts.items():
                layout = layout_cls()
                self.assertEqual(layout.report, report)
                ids = set(layout.item_ids())
                sections = [spec.ledger_section for spec in layout.sections()]
                self.assertEqual(len(sections), len(set(sections)), "one SectionSpec per ledger section")
                defined: set[str] = set()
                for item in layout.items:
                    if isinstance(item, ResultSpec):
                        for term, _sign in item.terms:
                            self.assertIn(term, defined, f"{template.key}/{report}: {item.id} uses {term} before it is defined")
                    if isinstance(item, RatioSpec):
                        self.assertIn(item.numerator, defined)
                        self.assertIn(item.denominator, defined)
                    if isinstance(item, BalanceSpec):
                        self.assertIn(item.flow_row, ids)
                    defined.add(item.id)
                for kpi in layout.kpis:
                    for row_id in kpi.rows:
                        self.assertIn(row_id, ids)
                    if kpi.ratio_row:
                        self.assertIn(kpi.ratio_row, ids)
                for row_id in (*layout.chart.inflow_rows, *layout.chart.outflow_rows, layout.chart.net_row):
                    self.assertIn(row_id, ids)


class TemplateErrorTypesTests(SimpleTestCase):
    def test_not_allowed_is_not_an_operating_system_error(self):
        from apps.modules.reports.services import TemplateNotAllowed

        self.assertFalse(issubclass(TemplateNotAllowed, OSError))
