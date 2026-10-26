"""Приход в инвестиционную кассу при подтверждении вложения «наличными»."""
from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.modules.cashier.models import CashRevenue
from apps.modules.investments.funding import INVESTOR_DEPOSIT_OPERATION, get_enabled_funding_config
from apps.modules.investments.models import ProjectInvestment, ProjectInvestmentApproval

logger = logging.getLogger(__name__)


def _revenue_author(project_investment: ProjectInvestment):
    approval = (
        ProjectInvestmentApproval.objects.filter(
            project_investment=project_investment,
            decision=ProjectInvestmentApproval.DECISION_APPROVED,
        )
        .select_related("approver_user")
        .order_by("-decided_at", "-id")
        .first()
    )
    if approval is not None:
        return approval.approver_user
    return get_user_model().objects.filter(pk=1).first()


def ensure_investor_cash_revenue(*, project_investment: ProjectInvestment) -> CashRevenue | None:
    """Создаёт (один раз) приход в инвестиционную кассу для подтверждённого вложения «наличными».

    Вызывается из post_save только на переходе confirmed False→True (см. signals.py).
    Возвращает None, если вложение не подтверждено, не наличное или режим выключен.
    """
    if not project_investment.confirmed or project_investment.funding_method != ProjectInvestment.FundingMethod.CASH:
        return None
    cfg = get_enabled_funding_config(project_investment.tenant)
    if cfg is None:
        return None
    if cfg.cash_wallet is None or cfg.cash_wallet.currency != project_investment.currency:
        # Дрейф конфигурации не должен блокировать подтверждение — только лог.
        logger.error(
            "Investor cash revenue skipped for project investment %s: cash wallet missing or currency mismatch.",
            project_investment.id,
        )
        return None

    existing = CashRevenue.objects.filter(
        tenant=project_investment.tenant,
        payload__project_investment_id=project_investment.id,
    ).first()
    if existing is not None:
        return existing

    author = _revenue_author(project_investment)
    if author is None:
        raise RuntimeError(f"No author available for investor cash revenue of investment {project_investment.id}.")

    now = timezone.now()
    return CashRevenue.objects.create(
        tenant=project_investment.tenant,
        wallet=cfg.cash_wallet,
        total_sum=project_investment.amount,
        currency=project_investment.currency,
        revenue_at=now,
        source_year=timezone.localtime(now).year,
        external_id=f"inv-{project_investment.id}",
        operation=INVESTOR_DEPOSIT_OPERATION,
        comment=f"На основании заявки на вложение №{project_investment.id}",
        payload={"project_investment_id": project_investment.id, "operation": INVESTOR_DEPOSIT_OPERATION},
        confirmed=True,
        created_by=author,
    )
