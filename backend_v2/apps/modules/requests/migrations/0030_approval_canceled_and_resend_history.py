import uuid

from django.db import migrations, models


def backfill_resend_batch_ids(apps, schema_editor):
    Approval = apps.get_model("requests", "Approval")
    for approval in Approval.objects.filter(resend_batch_id__isnull=True).only("id"):
        Approval.objects.filter(id=approval.id).update(resend_batch_id=uuid.uuid4())


class Migration(migrations.Migration):
    dependencies = [
        ("requests", "0029_requestapprovalconfig_draft_notification_action"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL("ALTER TABLE approvals ADD COLUMN IF NOT EXISTS resend_batch_id uuid NULL;"),
                migrations.RunSQL("ALTER TABLE approvals ADD COLUMN IF NOT EXISTS resend_key varchar(128) NULL;"),
                migrations.RunSQL("ALTER TABLE approvals ADD COLUMN IF NOT EXISTS replaced_approval_id bigint NULL;"),
                migrations.RunSQL(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_constraint WHERE conname = 'approvals_replaced_approval_id_fk'
                        ) THEN
                            ALTER TABLE approvals
                            ADD CONSTRAINT approvals_replaced_approval_id_fk
                            FOREIGN KEY (replaced_approval_id) REFERENCES approvals(id)
                            DEFERRABLE INITIALLY DEFERRED;
                        END IF;
                    END $$;
                    """
                ),
                migrations.RunSQL(
                    "CREATE INDEX IF NOT EXISTS approvals_resend_batch_idx ON approvals (resend_batch_id);"
                ),
                migrations.RunSQL("CREATE INDEX IF NOT EXISTS approvals_resend_key_idx ON approvals (resend_key);"),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="approval",
                    name="resend_batch_id",
                    field=models.UUIDField(blank=True, db_index=True, editable=False, null=True),
                ),
                migrations.AddField(
                    model_name="approval",
                    name="resend_key",
                    field=models.CharField(blank=True, db_index=True, max_length=128, null=True),
                ),
                migrations.AddField(
                    model_name="approval",
                    name="replaced_approval",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="resend_children",
                        to="requests.approval",
                    ),
                ),
            ],
        ),
        migrations.RunPython(backfill_resend_batch_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="approval",
            name="decision",
            field=models.CharField(
                choices=[
                    ("pending", "pending"),
                    ("approved", "approved"),
                    ("rejected", "rejected"),
                    ("canceled", "canceled"),
                ],
                default="pending",
                max_length=12,
            ),
        ),
        migrations.AlterField(
            model_name="approval",
            name="resend_batch_id",
            field=models.UUIDField(db_index=True, default=uuid.uuid4, editable=False),
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL("ALTER TABLE approvals DROP CONSTRAINT IF EXISTS approvals_request_step_approver_user_uniq;"),
                migrations.RunSQL(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_constraint WHERE conname = 'approvals_req_step_user_batch_uniq'
                        ) THEN
                            ALTER TABLE approvals
                            ADD CONSTRAINT approvals_req_step_user_batch_uniq
                            UNIQUE (request_id, step, approver_user_id, resend_batch_id);
                        END IF;
                    END $$;
                    """
                ),
            ],
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="approval",
                    name="approvals_request_step_approver_user_uniq",
                ),
                migrations.AddConstraint(
                    model_name="approval",
                    constraint=models.UniqueConstraint(
                        fields=("request", "step", "approver_user", "resend_batch_id"),
                        name="approvals_req_step_user_batch_uniq",
                    ),
                ),
            ],
        ),
    ]
