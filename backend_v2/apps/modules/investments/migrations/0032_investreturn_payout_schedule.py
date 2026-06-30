# Link each (possibly partial) InvestReturn to its InvestPayoutSchedule so that
# multiple payouts can accumulate against one scheduled amount. Confirmed payouts'
# sums roll up into InvestPayoutSchedule.payment_amount; is_paid flips when the
# cumulative confirmed total reaches the scheduled amount.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("investments", "0031_remove_legacy_message_fields"),
    ]

    operations = [
        # Free the "payout_schedule" reverse-accessor name (was created_return's related_name)
        # so the new forward FK below can use it. This reverse accessor was unused. No DB change.
        migrations.AlterField(
            model_name="investpayoutschedule",
            name="created_return",
            field=models.OneToOneField(
                blank=True,
                help_text="First InvestReturn created from this payout (one-click). Back-compat only.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="investments.investreturn",
            ),
        ),
        migrations.AddField(
            model_name="investreturn",
            name="payout_schedule",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Расписание выплат, к которому относится эта (возможно частичная) выплата. "
                    "Подтверждённые выплаты суммируются в payment_amount расписания; когда сумма "
                    "достигает amount — расписание закрывается как оплаченное."
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="returns",
                to="investments.investpayoutschedule",
            ),
        ),
    ]
