"""Report templates: a frontend view plus, for engine templates, one statement layout per report."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from apps.modules.reports.layouts import ProfessionalCashflowLayout, ProfessionalPnlLayout, StatementLayout
from apps.modules.reports.models import TEMPLATE_CLASSIC, TEMPLATE_PROFESSIONAL, default_allowed_templates

ENGINE_LEGACY = "legacy"
ENGINE_STATEMENT = "statement"


class TemplateSettingsInvalid(ValueError):
    """Default/allowed template settings cannot be saved."""


class TemplateNotFound(LookupError):
    """No template is registered under this key."""


class TemplateNotStatement(LookupError):
    """The template does not render this report through the statement engine."""


@dataclass(frozen=True)
class ReportTemplate:
    key: str
    label: str
    description: str
    engine: str
    layouts: Mapping[str, type[StatementLayout]] = field(default_factory=dict)
    reports: tuple[str, ...] = ("pnl", "cashflow")


REPORT_TEMPLATES: dict[str, ReportTemplate] = {
    template.key: template
    for template in (
        ReportTemplate(
            key=TEMPLATE_CLASSIC,
            label="Классический",
            description="Текущая страница: помесячная таблица и список операций.",
            engine=ENGINE_LEGACY,
        ),
        ReportTemplate(
            key=TEMPLATE_PROFESSIONAL,
            label="Профессиональный",
            description="Ключевые показатели, график, отчёт с итогами и сравнением, детализация операций.",
            engine=ENGINE_STATEMENT,
            layouts={"pnl": ProfessionalPnlLayout, "cashflow": ProfessionalCashflowLayout},
        ),
    )
}


def _normalized_keys(raw: Any) -> list[str]:
    keys: list[str] = []
    for value in raw if isinstance(raw, list) else []:
        key = str(value).strip()
        if key and key not in keys:
            keys.append(key)
    return keys


def validate_template_settings(default: str, allowed: list[str]) -> tuple[str, list[str]]:
    keys = _normalized_keys(allowed)
    if not keys:
        raise TemplateSettingsInvalid("Выберите хотя бы один шаблон.")
    unknown = [key for key in keys if key not in REPORT_TEMPLATES]
    if unknown:
        raise TemplateSettingsInvalid("Неизвестные шаблоны: " + ", ".join(unknown))
    default_key = str(default).strip()
    if default_key not in keys:
        raise TemplateSettingsInvalid("Шаблон по умолчанию должен быть среди разрешённых.")
    return default_key, keys


def tenant_template_settings(row: Any) -> tuple[str, list[str]]:
    """Registered templates only; a missing row or an empty list means Classic."""
    raw_allowed = getattr(row, "allowed_templates", None) if row is not None else None
    if not isinstance(raw_allowed, list):
        raw_allowed = default_allowed_templates()
    allowed = [key for key in _normalized_keys(raw_allowed) if key in REPORT_TEMPLATES] or [TEMPLATE_CLASSIC]
    default = str(getattr(row, "default_template", "") or "").strip() if row is not None else ""
    if default not in allowed:
        default = TEMPLATE_CLASSIC if TEMPLATE_CLASSIC in allowed else allowed[0]
    return default, allowed


def resolve_statement_layout(template_key: str, report: str) -> StatementLayout:
    template = REPORT_TEMPLATES.get(template_key)
    if template is None:
        raise TemplateNotFound(template_key)
    layout_cls = template.layouts.get(report)
    if template.engine != ENGINE_STATEMENT or layout_cls is None:
        raise TemplateNotStatement(template_key)
    return layout_cls()


def template_to_dict(template: ReportTemplate) -> dict[str, Any]:
    return {
        "key": template.key,
        "label": template.label,
        "description": template.description,
        "reports": list(template.reports),
        "engine": template.engine,
    }
