"""
Tests for per-stage telegram_chat on RequestApprovalStepConfig.

Covers:
  1. approval_bootstrap — recipient_id resolution (stage chat vs user fallback)
  2. approval_config_resolver — EffectivePaymentStepConfig.payment_chat_id derived from FK
  3. API read  — GET /api/requests/approval-config/ returns telegram_chat_id
  4. API write — PUT /api/requests/approval-config/ persists telegram_chat_id
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.modules.requests.approval_bootstrap import create_approval_rows_for_request
from apps.modules.requests.approval_config_resolver import (
    resolve_effective_payment_step_config_for_request,
)
from apps.modules.requests.models import (
    Approval,
    Request,
    RequestApprovalConfig,
    RequestApprovalPaymentTypeConfig,
    RequestApprovalPurposeExceptionConfig,
    RequestApprovalPurposeExceptionPurpose,
    RequestApprovalPurposeExceptionStepConfig,
    RequestApprovalPurposeExceptionStepApproverConfig,
    RequestApprovalStepApproverConfig,
    RequestApprovalStepConfig,
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    RequestPaymentPurposeConfig,
)
from apps.modules.telegram_approvals.models import TenantTelegramChat
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()

_STAGE_CHAT_STR = "-1009999000001"
_STAGE_CHAT_ID = _STAGE_CHAT_STR
_USER_CHAT_ID = 111
_USER_FROM_ID = 222


def _make_request(tenant, created_by, payment_type=Request.PAYMENT_TYPE_CASH):
    return Request.objects.create(
        tenant=tenant,
        created_by=created_by,
        title="Test",
        description="",
        amount=100,
        currency="UZS",
        payment_type=payment_type,
        urgency=Request.URGENCY_NORMAL,
        billing_date=date(2026, 1, 1),
        status=Request.STATUS_PROGRESS_1,
    )


def _make_tg_chat(tenant):
    return TenantTelegramChat.objects.create(
        tenant=tenant,
        name="Test Chat",
        chat_id=_STAGE_CHAT_STR,
    )


# ---------------------------------------------------------------------------
# 1. approval_bootstrap — recipient_id resolution
# ---------------------------------------------------------------------------

@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class ApprovalBootstrapPaymentChatIdTests(APITestCase):
    """
    create_approval_rows_for_request must:
    - use step.telegram_chat.chat_id as approver_recipient_id for PAYMENT steps when set
    - fall back to approver_user.telegram_chat_id when telegram_chat is None
    - always use approver_user.telegram_chat_id for SERIAL steps regardless of step config
    - keep approver_external_user_id = approver_user.telegram_from_id in all cases
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.admin = User.objects.create_user(username="pci_admin", password="x")
        self.requester = User.objects.create_user(username="pci_req", password="x")
        self.approver = User.objects.create_user(username="pci_appr", password="x")
        self.approver.telegram_chat_id = _USER_CHAT_ID
        self.approver.telegram_from_id = _USER_FROM_ID
        self.approver.save(update_fields=["telegram_chat_id", "telegram_from_id"])

        for u in (self.admin, self.requester, self.approver):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)

        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.requester, role=TenantUserRole.ROLE_REQUESTER)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.approver, role=TenantUserRole.ROLE_APPROVER)

        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)

        self.appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        self.pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=self.appr_cfg,
            payment_type=Request.PAYMENT_TYPE_CASH,
            is_enabled=True,
        )
        self.tg_chat = _make_tg_chat(self.tenant)

    # --- payment step with stage chat set ---

    def test_payment_step_uses_stage_chat_id_not_user_chat_id(self):
        step = RequestApprovalStepConfig.objects.create(
            payment_type_config=self.pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            telegram_chat=self.tg_chat,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step, approver_user=self.approver)

        req = _make_request(self.tenant, self.requester)
        n = create_approval_rows_for_request(req)

        self.assertEqual(n, 1)
        approval = Approval.objects.get(request=req, approver_user=self.approver)
        self.assertEqual(approval.approver_recipient_id, _STAGE_CHAT_ID)
        self.assertEqual(approval.approver_external_user_id, _USER_FROM_ID)

    def test_payment_step_stage_chat_overrides_even_when_user_has_different_chat_id(self):
        other_chat_id = 9998887776
        self.approver.telegram_chat_id = other_chat_id
        self.approver.save(update_fields=["telegram_chat_id"])

        step = RequestApprovalStepConfig.objects.create(
            payment_type_config=self.pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            telegram_chat=self.tg_chat,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step, approver_user=self.approver)

        req = _make_request(self.tenant, self.requester)
        create_approval_rows_for_request(req)

        approval = Approval.objects.get(request=req, approver_user=self.approver)
        self.assertEqual(approval.approver_recipient_id, _STAGE_CHAT_ID)
        self.assertNotEqual(approval.approver_recipient_id, other_chat_id)

    # --- payment step with no chat (fallback) ---

    def test_payment_step_without_stage_chat_falls_back_to_user_chat_id(self):
        step = RequestApprovalStepConfig.objects.create(
            payment_type_config=self.pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            telegram_chat=None,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step, approver_user=self.approver)

        req = _make_request(self.tenant, self.requester)
        create_approval_rows_for_request(req)

        approval = Approval.objects.get(request=req, approver_user=self.approver)
        self.assertEqual(approval.approver_recipient_id, str(_USER_CHAT_ID))
        self.assertEqual(approval.approver_external_user_id, _USER_FROM_ID)

    # --- serial step ignores stage chat ---

    def test_serial_step_always_uses_user_chat_id_regardless_of_any_config(self):
        step = RequestApprovalStepConfig.objects.create(
            payment_type_config=self.pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            is_enabled=True,
            telegram_chat=self.tg_chat,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step, approver_user=self.approver)

        req = _make_request(self.tenant, self.requester)
        create_approval_rows_for_request(req)

        approval = Approval.objects.get(request=req, approver_user=self.approver)
        self.assertEqual(approval.approver_recipient_id, str(_USER_CHAT_ID))

    # --- multiple approvers share the same stage chat ---

    def test_multiple_approvers_on_payment_step_all_get_stage_chat_id(self):
        second_approver = User.objects.create_user(username="pci_appr2", password="x")
        second_approver.telegram_chat_id = 555
        second_approver.telegram_from_id = 666
        second_approver.save(update_fields=["telegram_chat_id", "telegram_from_id"])
        TenantMembership.objects.create(tenant=self.tenant, user=second_approver, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=second_approver, role=TenantUserRole.ROLE_APPROVER)

        step = RequestApprovalStepConfig.objects.create(
            payment_type_config=self.pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            telegram_chat=self.tg_chat,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step, approver_user=self.approver)
        RequestApprovalStepApproverConfig.objects.create(step_config=step, approver_user=second_approver)

        req = _make_request(self.tenant, self.requester)
        n = create_approval_rows_for_request(req)
        self.assertEqual(n, 2)

        for approval in Approval.objects.filter(request=req):
            self.assertEqual(
                approval.approver_recipient_id,
                _STAGE_CHAT_ID,
                f"Approver {approval.approver_user_id} should use stage chat_id",
            )

    # --- from_id is always user-level ---

    def test_from_id_always_user_level_even_with_stage_chat(self):
        step = RequestApprovalStepConfig.objects.create(
            payment_type_config=self.pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            telegram_chat=self.tg_chat,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step, approver_user=self.approver)

        req = _make_request(self.tenant, self.requester)
        create_approval_rows_for_request(req)

        approval = Approval.objects.get(request=req, approver_user=self.approver)
        self.assertEqual(approval.approver_external_user_id, _USER_FROM_ID)

    # --- purpose-exception step ---

    def test_purpose_exception_payment_step_uses_stage_chat_id(self):
        form_cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_form_cfg = RequestFormPaymentTypeConfig.objects.create(
            config=form_cfg, payment_type=Request.PAYMENT_TYPE_CASH, is_enabled=True
        )
        purpose = RequestPaymentPurposeConfig.objects.create(
            payment_type_config=pt_form_cfg,
            name="Special purpose",
            category="",
            is_active=True,
        )

        exc = RequestApprovalPurposeExceptionConfig.objects.create(
            payment_type_config=self.pt_cfg,
            name="Special exc",
            is_enabled=True,
        )
        RequestApprovalPurposeExceptionPurpose.objects.create(
            exception_config=exc,
            payment_type_config=self.pt_cfg,
            payment_purpose=purpose,
        )
        exc_step = RequestApprovalPurposeExceptionStepConfig.objects.create(
            exception_config=exc,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            telegram_chat=self.tg_chat,
        )
        RequestApprovalPurposeExceptionStepApproverConfig.objects.create(
            step_config=exc_step, approver_user=self.approver
        )

        req = _make_request(self.tenant, self.requester)
        req.payment_purpose = "Special purpose"
        req.save(update_fields=["payment_purpose"])

        create_approval_rows_for_request(req)

        approval = Approval.objects.get(request=req, approver_user=self.approver)
        self.assertEqual(approval.approver_recipient_id, _STAGE_CHAT_ID)
        self.assertEqual(approval.approver_external_user_id, _USER_FROM_ID)

    def test_purpose_exception_payment_step_without_stage_chat_falls_back_to_user(self):
        form_cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_form_cfg = RequestFormPaymentTypeConfig.objects.create(
            config=form_cfg, payment_type=Request.PAYMENT_TYPE_CASH, is_enabled=True
        )
        purpose = RequestPaymentPurposeConfig.objects.create(
            payment_type_config=pt_form_cfg, name="Normal purpose", category="", is_active=True
        )

        exc = RequestApprovalPurposeExceptionConfig.objects.create(
            payment_type_config=self.pt_cfg, name="No chat exc", is_enabled=True
        )
        RequestApprovalPurposeExceptionPurpose.objects.create(
            exception_config=exc,
            payment_type_config=self.pt_cfg,
            payment_purpose=purpose,
        )
        exc_step = RequestApprovalPurposeExceptionStepConfig.objects.create(
            exception_config=exc,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            telegram_chat=None,
        )
        RequestApprovalPurposeExceptionStepApproverConfig.objects.create(
            step_config=exc_step, approver_user=self.approver
        )

        req = _make_request(self.tenant, self.requester)
        req.payment_purpose = "Normal purpose"
        req.save(update_fields=["payment_purpose"])

        create_approval_rows_for_request(req)

        approval = Approval.objects.get(request=req, approver_user=self.approver)
        self.assertEqual(approval.approver_recipient_id, str(_USER_CHAT_ID))


# ---------------------------------------------------------------------------
# 2. approval_config_resolver — EffectivePaymentStepConfig.payment_chat_id
# ---------------------------------------------------------------------------

@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class ResolverPaymentChatIdTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Res", subdomain="res", is_active=True)
        self.admin = User.objects.create_user(username="res_admin", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)

        self.appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        self.pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=self.appr_cfg,
            payment_type=Request.PAYMENT_TYPE_CASH,
            is_enabled=True,
        )
        self.tg_chat = _make_tg_chat(self.tenant)

    def test_effective_config_includes_payment_chat_id_when_set(self):
        step = RequestApprovalStepConfig.objects.create(
            payment_type_config=self.pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            telegram_chat=self.tg_chat,
        )
        RequestApprovalStepApproverConfig.objects.create(
            step_config=step,
            approver_user=self.admin,
        )
        req = _make_request(self.tenant, self.admin)

        cfg = resolve_effective_payment_step_config_for_request(
            request_obj=req,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
        )

        self.assertIsNotNone(cfg)
        self.assertEqual(cfg.payment_chat_id, _STAGE_CHAT_ID)

    def test_effective_config_payment_chat_id_is_none_when_not_set(self):
        step = RequestApprovalStepConfig.objects.create(
            payment_type_config=self.pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            telegram_chat=None,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step, approver_user=self.admin)
        req = _make_request(self.tenant, self.admin)

        cfg = resolve_effective_payment_step_config_for_request(
            request_obj=req,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
        )

        self.assertIsNotNone(cfg)
        self.assertIsNone(cfg.payment_chat_id)

    def test_resolver_returns_none_for_serial_step(self):
        step = RequestApprovalStepConfig.objects.create(
            payment_type_config=self.pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            is_enabled=True,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step, approver_user=self.admin)
        req = _make_request(self.tenant, self.admin)

        cfg = resolve_effective_payment_step_config_for_request(
            request_obj=req,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
        )

        self.assertIsNone(cfg)


# ---------------------------------------------------------------------------
# 3 & 4. API read/write — GET and PUT /api/requests/approval-config/
# ---------------------------------------------------------------------------

@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class ApprovalConfigApiPaymentChatIdTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.admin = User.objects.create_user(username="api_admin", password="x")
        self.approver = User.objects.create_user(username="api_appr", password="x")
        self.approver.telegram_chat_id = _USER_CHAT_ID
        self.approver.telegram_from_id = _USER_FROM_ID
        self.approver.save(update_fields=["telegram_chat_id", "telegram_from_id"])

        for u in (self.admin, self.approver):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)

        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.approver, role=TenantUserRole.ROLE_APPROVER)

        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)
        self.host = "acme.example.com"
        self.tg_chat = _make_tg_chat(self.tenant)

    # --- write then read ---

    def test_put_saves_telegram_chat_id_for_payment_step(self):
        self.client.force_authenticate(self.admin)
        payload = {
            "payment_types": [
                {
                    "payment_type": "Наличные",
                    "is_enabled": True,
                    "steps": [
                        {
                            "step": 1,
                            "step_type": "payment",
                            "is_enabled": True,
                            "approver_user_ids": [self.approver.id],
                            "payment_action_mode": "callback",
                            "payment_webapp_url": "",
                            "telegram_chat_id": self.tg_chat.pk,
                        }
                    ],
                }
            ]
        }
        res = self.client.put(
            "/api/requests/approval-config/",
            payload,
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)

        step = RequestApprovalStepConfig.objects.get(
            payment_type_config__config__tenant=self.tenant,
            payment_type_config__payment_type="Наличные",
            step=1,
        )
        self.assertEqual(step.telegram_chat_id, self.tg_chat.pk)

    def test_get_returns_telegram_chat_id_in_step(self):
        appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type="Наличные", is_enabled=True
        )
        step = RequestApprovalStepConfig.objects.create(
            payment_type_config=pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            telegram_chat=self.tg_chat,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step, approver_user=self.approver)

        self.client.force_authenticate(self.admin)
        res = self.client.get("/api/requests/approval-config/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)

        cash_pt = next(
            pt for pt in res.data["payment_types"] if pt["payment_type"] == "Наличные"
        )
        self.assertEqual(len(cash_pt["steps"]), 1)
        self.assertEqual(cash_pt["steps"][0]["telegram_chat_id"], self.tg_chat.pk)

    def test_put_telegram_chat_id_none_clears_field(self):
        appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type="Наличные", is_enabled=True
        )
        RequestApprovalStepConfig.objects.create(
            payment_type_config=pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            telegram_chat=self.tg_chat,
        )

        self.client.force_authenticate(self.admin)
        payload = {
            "payment_types": [
                {
                    "payment_type": "Наличные",
                    "is_enabled": True,
                    "steps": [
                        {
                            "step": 1,
                            "step_type": "payment",
                            "is_enabled": True,
                            "approver_user_ids": [self.approver.id],
                            "payment_action_mode": "callback",
                            "telegram_chat_id": None,
                        }
                    ],
                }
            ]
        }
        res = self.client.put(
            "/api/requests/approval-config/",
            payload,
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)

        step = RequestApprovalStepConfig.objects.get(
            payment_type_config__config__tenant=self.tenant,
            payment_type_config__payment_type="Наличные",
            step=1,
        )
        self.assertIsNone(step.telegram_chat_id)

    def test_put_omitting_telegram_chat_id_defaults_to_none(self):
        """telegram_chat_id is optional — omitting it must not cause a 400."""
        self.client.force_authenticate(self.admin)
        payload = {
            "payment_types": [
                {
                    "payment_type": "Наличные",
                    "is_enabled": True,
                    "steps": [
                        {
                            "step": 1,
                            "step_type": "payment",
                            "is_enabled": True,
                            "approver_user_ids": [self.approver.id],
                            "payment_action_mode": "callback",
                            # telegram_chat_id deliberately omitted
                        }
                    ],
                }
            ]
        }
        res = self.client.put(
            "/api/requests/approval-config/",
            payload,
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)
        step = RequestApprovalStepConfig.objects.get(
            payment_type_config__config__tenant=self.tenant,
            payment_type_config__payment_type="Наличные",
            step=1,
        )
        self.assertIsNone(step.telegram_chat_id)

    def test_get_returns_telegram_chat_id_null_when_not_set(self):
        appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type="Наличные", is_enabled=True
        )
        step = RequestApprovalStepConfig.objects.create(
            payment_type_config=pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            telegram_chat=None,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step, approver_user=self.approver)

        self.client.force_authenticate(self.admin)
        res = self.client.get("/api/requests/approval-config/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        cash_pt = next(pt for pt in res.data["payment_types"] if pt["payment_type"] == "Наличные")
        self.assertIsNone(cash_pt["steps"][0]["telegram_chat_id"])

    # --- purpose-exception steps ---

    def test_put_saves_telegram_chat_id_for_purpose_exception_step(self):
        form_cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_form_cfg = RequestFormPaymentTypeConfig.objects.create(
            config=form_cfg, payment_type="Наличные", is_enabled=True
        )
        purpose = RequestPaymentPurposeConfig.objects.create(
            payment_type_config=pt_form_cfg, name="Exc purpose", category="", is_active=True
        )

        appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type="Наличные", is_enabled=True
        )

        self.client.force_authenticate(self.admin)
        payload = {
            "payment_types": [
                {
                    "payment_type": "Наличные",
                    "is_enabled": True,
                    "steps": [],
                    "purpose_exceptions": [
                        {
                            "name": "exc1",
                            "is_enabled": True,
                            "payment_purpose_ids": [purpose.id],
                            "steps": [
                                {
                                    "step": 1,
                                    "step_type": "payment",
                                    "is_enabled": True,
                                    "approver_user_ids": [self.approver.id],
                                    "payment_action_mode": "callback",
                                    "telegram_chat_id": self.tg_chat.pk,
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        res = self.client.put(
            "/api/requests/approval-config/",
            payload,
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)

        exc_step = RequestApprovalPurposeExceptionStepConfig.objects.get(
            exception_config__payment_type_config__config__tenant=self.tenant,
            step=1,
        )
        self.assertEqual(exc_step.telegram_chat_id, self.tg_chat.pk)

    def test_get_returns_telegram_chat_id_for_purpose_exception_step(self):
        appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type="Наличные", is_enabled=True
        )
        form_cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_form_cfg = RequestFormPaymentTypeConfig.objects.create(
            config=form_cfg, payment_type="Наличные", is_enabled=True
        )
        purpose = RequestPaymentPurposeConfig.objects.create(
            payment_type_config=pt_form_cfg, name="E purpose", category="", is_active=True
        )
        exc = RequestApprovalPurposeExceptionConfig.objects.create(
            payment_type_config=pt_cfg, name="exc", is_enabled=True
        )
        RequestApprovalPurposeExceptionPurpose.objects.create(
            exception_config=exc, payment_type_config=pt_cfg, payment_purpose=purpose
        )
        exc_step = RequestApprovalPurposeExceptionStepConfig.objects.create(
            exception_config=exc,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            telegram_chat=self.tg_chat,
        )
        RequestApprovalPurposeExceptionStepApproverConfig.objects.create(
            step_config=exc_step, approver_user=self.approver
        )

        self.client.force_authenticate(self.admin)
        res = self.client.get("/api/requests/approval-config/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)

        cash_pt = next(pt for pt in res.data["payment_types"] if pt["payment_type"] == "Наличные")
        exc_steps = cash_pt["purpose_exceptions"][0]["steps"]
        self.assertEqual(len(exc_steps), 1)
        self.assertEqual(exc_steps[0]["telegram_chat_id"], self.tg_chat.pk)

    # --- round-trip: PUT then GET returns same value ---

    def test_round_trip_put_then_get_preserves_telegram_chat_id(self):
        self.client.force_authenticate(self.admin)
        payload = {
            "payment_types": [
                {
                    "payment_type": "Перечисление",
                    "is_enabled": True,
                    "steps": [
                        {
                            "step": 1,
                            "step_type": "payment",
                            "is_enabled": True,
                            "approver_user_ids": [self.approver.id],
                            "payment_action_mode": "callback",
                            "telegram_chat_id": self.tg_chat.pk,
                        }
                    ],
                }
            ]
        }
        put_res = self.client.put(
            "/api/requests/approval-config/",
            payload,
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(put_res.status_code, 200, put_res.content)

        get_res = self.client.get("/api/requests/approval-config/", HTTP_HOST=self.host)
        self.assertEqual(get_res.status_code, 200)
        transfer_pt = next(
            pt for pt in get_res.data["payment_types"] if pt["payment_type"] == "Перечисление"
        )
        self.assertEqual(transfer_pt["steps"][0]["telegram_chat_id"], self.tg_chat.pk)
