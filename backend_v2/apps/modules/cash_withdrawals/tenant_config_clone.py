"""
Cash-withdrawals part of `clone_tenant_config` (see apps.tenants.config_clone):
timings, chats, confirmers and alert recipients. Rules point at the branch's
own wallets, so they are not copied and the config is created inactive.
"""

from __future__ import annotations

from apps.modules.cash_withdrawals.models import (
    CashWithdrawalAlertRecipient,
    CashWithdrawalConfig,
    CashWithdrawalConfirmer,
)


def clone(ctx) -> None:
    src = CashWithdrawalConfig.objects.filter(tenant=ctx.source).first()
    if src is None or CashWithdrawalConfig.objects.filter(tenant=ctx.target).exists():
        return
    member_ids = ctx.target_member_ids()
    dst = CashWithdrawalConfig.objects.create(
        tenant=ctx.target,
        is_active=False,
        card_telegram_chat=ctx.chat(src.card_telegram_chat),
        alert_telegram_chat=ctx.chat(src.alert_telegram_chat),
        alert_after_days=src.alert_after_days,
        alert_repeat_every_days=src.alert_repeat_every_days,
        alert_hour=src.alert_hour,
    )
    for model in (CashWithdrawalConfirmer, CashWithdrawalAlertRecipient):
        user_ids = model.objects.filter(config=src, user_id__in=member_ids).values_list("user_id", flat=True)
        model.objects.bulk_create([model(config=dst, user_id=uid) for uid in user_ids])
    ctx.change("Инкассация: настройки скопированы (выключено).")
    if src.rules.exists():
        ctx.warn("Инкассация: правила привязаны к кассам филиала — задайте свои кассы и включите вручную.")
