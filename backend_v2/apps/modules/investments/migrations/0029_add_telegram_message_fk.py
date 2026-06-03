# Add telegram_message FK to investment approval models.
# Data migration (0030) copies existing gateway_message_id → TelegramMessage.
# Column removal (0031) happens after data is safely migrated.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("investments", "0028_remove_investpayoutschedule_created_request_and_more"),
        ("telegram_approvals", "0003_notification"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                # --- InvestmentReturnApproval ---
                migrations.AddField(
                    model_name="investmentreturnapproval",
                    name="telegram_message",
                    field=models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="investment_return_approval",
                        to="telegram_approvals.telegrammessage",
                    ),
                ),
                # --- ProjectInvestmentApproval ---
                migrations.AddField(
                    model_name="projectinvestmentapproval",
                    name="telegram_message",
                    field=models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="project_investment_approval",
                        to="telegram_approvals.telegrammessage",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE investment_return_approvals
                            ADD COLUMN IF NOT EXISTS telegram_message_id bigint NULL
                                REFERENCES telegram_messages(id)
                                ON DELETE SET NULL
                                DEFERRABLE INITIALLY DEFERRED;
                        CREATE UNIQUE INDEX IF NOT EXISTS investment_return_approvals_telegram_message_id_key
                            ON investment_return_approvals (telegram_message_id)
                            WHERE telegram_message_id IS NOT NULL;

                        ALTER TABLE project_investment_approvals
                            ADD COLUMN IF NOT EXISTS telegram_message_id bigint NULL
                                REFERENCES telegram_messages(id)
                                ON DELETE SET NULL
                                DEFERRABLE INITIALLY DEFERRED;
                        CREATE UNIQUE INDEX IF NOT EXISTS project_investment_approvals_telegram_message_id_key
                            ON project_investment_approvals (telegram_message_id)
                            WHERE telegram_message_id IS NOT NULL;
                    """,
                    reverse_sql="""
                        ALTER TABLE investment_return_approvals
                            DROP COLUMN IF EXISTS telegram_message_id;
                        ALTER TABLE project_investment_approvals
                            DROP COLUMN IF EXISTS telegram_message_id;
                    """,
                ),
            ],
        ),
    ]
