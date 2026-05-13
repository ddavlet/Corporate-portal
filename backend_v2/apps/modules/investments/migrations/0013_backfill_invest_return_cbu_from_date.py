from decimal import Decimal

from django.db import migrations


def forwards_backfill_invest_return_cbu(apps, schema_editor):
    """
    Заполняет cbu_usd_uzs_rate и sum_uzs по курсам ЦБ РУз на дату поля ``date`` каждой записи.

    Требуется сетевой доступ к cbu.uz на время применения миграции.
    """
    from apps.modules.investments.services import (
        CbuRateFetchError,
        clamp_rate_date_to_cbu_availability,
        fetch_cbu_rows_for_date,
        invest_return_cbu_usd_rate_and_sum_uzs_from_bulletin,
    )

    InvestReturn = apps.get_model("investments", "InvestReturn")

    dates_qs = InvestReturn.objects.values_list("date", flat=True).distinct()
    effective_dates = sorted(
        {clamp_rate_date_to_cbu_availability(requested=d) for d in dates_qs if d is not None}
    )

    bulletin_by_date: dict = {}
    for d in effective_dates:
        try:
            bulletin_by_date[d] = fetch_cbu_rows_for_date(rate_date=d)
        except CbuRateFetchError as exc:
            raise RuntimeError(
                f"Миграция backfill invest_returns: не удалось загрузить курсы ЦБ на {d}: {exc}"
            ) from exc

    for ir in InvestReturn.objects.iterator():
        d = clamp_rate_date_to_cbu_availability(requested=ir.date)
        rows = bulletin_by_date.get(d)
        if not rows:
            raise RuntimeError(f"Миграция: нет бюллетеня ЦБ для даты {d} (invest_return id={ir.pk}).")
        sum_val = Decimal(str(ir.sum))
        currency = str(ir.currency or "USD").strip().upper()
        try:
            cbu_usd, sum_uzs = invest_return_cbu_usd_rate_and_sum_uzs_from_bulletin(
                sum_val=sum_val,
                currency=currency,
                rows=rows,
            )
        except CbuRateFetchError as exc:
            raise RuntimeError(
                f"Миграция: invest_return id={ir.pk}, дата={d}, валюта={currency!r}: {exc}"
            ) from exc
        InvestReturn.objects.filter(pk=ir.pk).update(
            cbu_usd_uzs_rate=cbu_usd,
            sum_uzs=sum_uzs,
        )


def noop_reverse(apps, schema_editor):
    """Откат не восстанавливает прежние суммы (данные не удаляются)."""
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0012_investreturn_cbu_usd_uzs_rate"),
    ]

    operations = [
        migrations.RunPython(forwards_backfill_invest_return_cbu, noop_reverse),
    ]
