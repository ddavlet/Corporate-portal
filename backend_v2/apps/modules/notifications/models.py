from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.tenants.models import Tenant


class PushSubscription(models.Model):
    """Browser Web Push subscription of a user (one per device/browser).

    Not bound to a company: the subscription is made on the shared portal host and
    carries notifications of all companies of the user. Rows are never deleted:
    a gone or unsubscribed endpoint gets `revoked_at`.
    """

    REVOKE_REASON_USER = "user"
    REVOKE_REASON_GONE = "gone"
    # Older active subscriptions above the per-user limit.
    REVOKE_REASON_LIMIT = "limit"
    # Endpoint outside the push-service allow-list (checked again before each send).
    REVOKE_REASON_NOT_ALLOWED = "not_allowed"
    # The user was deactivated.
    REVOKE_REASON_INACTIVE = "inactive"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_subscriptions")
    endpoint = models.TextField()
    # sha256 of `endpoint`: endpoints are long URLs, a unique btree index on them could hit the row size limit.
    endpoint_hash = models.CharField(max_length=64, unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    user_agent = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.CharField(max_length=20, blank=True, default="")
    # Set by approval hooks (the request thread never sends); the cron run sends and clears it.
    sync_requested_at = models.DateTimeField(null=True, blank=True)
    # Last finished sync of the user: the catch-up run goes from the longest-unsynced users.
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "push_subscriptions"

    def __str__(self):
        state = "revoked" if self.revoked_at else "active"
        return f"PushSubscription(id={self.pk}, user={self.user_id}, {state})"


class ActionItemPushState(models.Model):
    """Which action items a user was already notified about (one row per user and tag).

    `tag` is `<subdomain>:<kind>-<id>`, unique across companies. `step_key` is the approval
    step the push was about (`<step>:<approval_id>`): when the same user is the approver of the
    next step too, the tag stays open but the step changes, and that is a new push. `closed_at`
    is set when the item is no longer waiting on the user; a new step on the same object reopens the row.
    """

    # Both FKs are covered by the indexes below (tenant by (tenant, user), user by (user, tag)).
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="action_item_push_states", db_index=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="action_item_push_states",
        db_index=False,
    )
    tag = models.CharField(max_length=128)
    step_key = models.CharField(max_length=64, blank=True, default="")
    sent_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "action_item_push_states"
        constraints = [
            models.UniqueConstraint(fields=["user", "tag"], name="push_state_user_tag_uniq"),
        ]
        indexes = [
            models.Index(fields=["tenant", "user"], name="push_state_tenant_user_idx"),
            # affected_user_ids: open states of one tag (the unique index leads with user).
            models.Index(fields=["tag"], condition=Q(closed_at__isnull=True), name="push_state_open_tag_idx"),
        ]

    def __str__(self):
        return f"ActionItemPushState(user={self.user_id}, tag={self.tag!r}, closed={self.closed_at is not None})"
