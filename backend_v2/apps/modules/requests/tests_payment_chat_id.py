"""
Tests for per-stage payment_chat_id on RequestApprovalStepConfig.

Covers:
  1. approval_bootstrap — recipient_id resolution (stage vs user fallback)
  2. _coerce_payment_chat_id helper
  3. approval_config_resolver — EffectivePaymentStepConfig includes payment_chat_id
  4. API read  — GET /api/requests/approval-config/ returns payment_chat_id
  5. API write — PUT /api/requests/approval-config/ persists payment_chat_id
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.exceptions import ValidationError
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
from apps.modules.requests.views import _coerce_payment_chat_id
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()

_STAGE_CHAT_ID = -1009999000001
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


# ---------------------------------------------------------------------------
# 1. _coerce_payment_chat_id helper
# ---------------------------------------------------------------------------

class CoercePaymentChatIdTests(APITestCase):

    def test_none_returns_none(self):
        self.assertIsNone(_coerce_payment_chat_id(None))

    def test_integer_returned_as_is(self):
        self.assertEqual(_coerce_payment_chat_id(42), 42)

    def test_negative_integer(self):
        self.assertEqual(_coerce_payment_chat_id(-1001234567890), -1001234567890)

    def test_valid_string_coerced_to_int(self):
        self.assertEqual(_coerce_payment_chat_id("-1009999000001"), -1009999000001)

    def test_empty_string_returns_none(self):
        self.assertIsNone(_coerce_payment_chat_id(""))

    def test_whitespace_only_string_returns_none(self):
        self.assertIsNone(_coerce_payment_chat_id("   "))

    def test_non_numeric_string_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            _coerce_payment_chat_id("not-a-number")

    def test_float_string_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            _coerce_payment_chat_id("3.14")

    def test_zero_is_valid(self):
        self.assertEqual(_coerce_payment_chat_id(0), 0)

    def test_string_zero_is_valid(self):
        self.assertEqual(_coerce_payment_chat_id("0"), 0)


# ---------------------------------------------------------------------------
# 2. approval_bootstrap — recipient_id resolution
# ---------------------------------------------------------------------------

@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class ApprovalBootstrapPaymentChatIdTests(APITestCase):
    """
    create_approval_rows_for_request must:
    - use step.payment_chat_id as approver_recipient_id for PAYMENT steps when set
    - fall back to approver_user.telegram_chat_id when payment_chat_id is None
    - always use approver_user.telegram_chat_id for SERIAL steps regardless of any step config
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

    # --- payment step with stage chat_id set ---

    def test_payment_step_uses_stage_chat_id_not_user_chat_id(self):
        step = RequestApprovalStepConfig.objects.create(
            payment_type_config=self.pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            payment_chat_id=_STAGE_CHAT_ID,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step, approver_user=self.approver)

        req = _make_request(self.tenant, self.requester)
        n = create_approval_rows_for_request(req)

        self.assertEqual(n, 1)
        approval = Approval.objects.get(request=req, approver_user=self.approver)
        self.assertEqual(approval.approver_recipient_id, _STAGE_CHAT_ID)
        # from_id must remain user-level (identity check unchanged)
        self.assertEqual(approval.approver_external_user_id, _USER_FROM_ID)

    def test_payment_step_stage_chat_id_overrides_even_when_user_has_different_chat_id(self):
        other_chat_id = 9998887776
        self.approver.telegram_chat_id = other_chat_id
        self.approver.save(update_fields=["telegram_chat_id"])

        step = RequestApprovalStepConfig.objects.create(
            payment_type_config=self.pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            payment_chat_id=_STAGE_CHAT_ID,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step, approver_user=self.approver)

        req = _make_request(self.tenant, self.requester)
        create_approval_rows_for_request(req)

        approval = Approval.objects.get(request=req, approver_user=self.approver)
        self.assertEqual(approval.approver_recipient_id, _STAGE_CHAT_ID)
        self.assertNotEqual(approval.approver_recipient_id, other_chat_id)

    # --- payment step with payment_chat_id = None (fallback) ---

    def test_payment_step_without_stage_chat_id_falls_back_to_user_chat_id(self):
        step = RequestApprovalStepConfig.objects.create(
            payment_type_config=self.pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            payment_chat_id=None,  # no stage override
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step, approver_user=self.approver)

        req = _make_request(self.tenant, self.requester)
        create_approval_rows_for_request(req)

        approval = Approval.objects.get(request=req, approver_user=self.approver)
        self.assertEqual(approval.approver_recipient_id, _USER_CHAT_ID)
        self.assertEqual(approval.approver_external_user_id, _USER_FROM_ID)

    # --- serial step is unaffected ---

    def test_serial_step_always_uses_user_chat_id_regardless_of_any_config(self):
        step = RequestApprovalStepConfig.objects.create(
            payment_type_config=self.pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            is_enabled=True,
            # payment_chat_id is irrelevant for serial steps; set it anyway to confirm it's ignored
            payment_chat_id=_STAGE_CHAT_ID,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step, approver_user=self.approver)

        req = _make_request(self.tenant, self.requester)
        create_approval_rows_for_request(req)

        approval = Approval.objects.get(request=req, approver_user=self.approver)
        self.assertEqual(approval.approver_recipient_id, _USER_CHAT_ID)

    # --- multiple approvers share the same stage chat_id ---

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
            payment_chat_id=_STAGE_CHAT_ID,
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

    def test_from_id_always_user_level_even_with_stage_chat_id(self):
        step = RequestApprovalStepConfig.objects.create(
            payment_type_config=self.pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            payment_chat_id=_STAGE_CHAT_ID,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step, approver_user=self.approver)

        req = _make_request(self.tenant, self.requester)
        create_approval_rows_for_request(req)

        approval = Approval.objects.get(request=req, approver_user=self.approver)
        self.assertEqual(approval.approver_external_user_id, _USER_FROM_ID)

    # --- purpose-exception step uses payment_chat_id ---

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
            payment_chat_id=_STAGE_CHAT_ID,
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

    def test_purpose_exception_payment_step_without_stage_chat_id_falls_back_to_user(self):
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
            payment_chat_id=None,
        )
        RequestApprovalPurposeExceptionStepApproverConfig.objects.create(
            step_config=exc_step, approver_user=self.approver
        )

        req = _make_request(self.tenant, self.requester)
        req.payment_purpose = "Normal purpose"
        req.save(update_fields=["payment_purpose"])

        create_approval_rows_for_request(req)

        approval = Approval.objects.get(request=req, approver_user=self.approver)
        self.assertEqual(approval.approver_recipient_id, _USER_CHAT_ID)


# ---------------------------------------------------------------------------
# 3. approval_config_resolver — EffectivePaymentStepConfig includes payment_chat_id
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

    def test_effective_config_includes_payment_chat_id_when_set(self):
        step = RequestApprovalStepConfig.objects.create(
            payment_type_config=self.pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            payment_chat_id=_STAGE_CHAT_ID,
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
            payment_chat_id=None,
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
# 4 & 5. API read/write — GET and PUT /api/requests/approval-config/
# ---------------------------------------------------------------------------

@override_settings(BASE_DOMAIN="example.com", N8N_TOKEN="", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
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

    # --- write then read ---

    def test_put_saves_payment_chat_id_for_payment_step(self):
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
                            "payment_chat_id": _STAGE_CHAT_ID,
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
        self.assertEqual(step.payment_chat_id, _STAGE_CHAT_ID)

    def test_get_returns_payment_chat_id_in_step(self):
        # Seed DB directly
        appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type="Наличные", is_enabled=True
        )
        step = RequestApprovalStepConfig.objects.create(
            payment_type_config=pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            payment_chat_id=_STAGE_CHAT_ID,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step, approver_user=self.approver)

        self.client.force_authenticate(self.admin)
        res = self.client.get("/api/requests/approval-config/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)

        cash_pt = next(
            pt for pt in res.data["payment_types"] if pt["payment_type"] == "Наличные"
        )
        self.assertEqual(len(cash_pt["steps"]), 1)
        self.assertEqual(cash_pt["steps"][0]["payment_chat_id"], _STAGE_CHAT_ID)

    def test_put_payment_chat_id_none_clears_field(self):
        # Seed with a value then overwrite with null
        appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type="Наличные", is_enabled=True
        )
        RequestApprovalStepConfig.objects.create(
            payment_type_config=pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            payment_chat_id=_STAGE_CHAT_ID,
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
                            "payment_chat_id": None,
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
        self.assertIsNone(step.payment_chat_id)

    def test_put_omitting_payment_chat_id_defaults_to_none(self):
        """payment_chat_id is optional — omitting it must not cause a 400."""
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
                            # payment_chat_id deliberately omitted
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
        self.assertIsNone(step.payment_chat_id)

    def test_get_returns_payment_chat_id_null_when_not_set(self):
        appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type="Наличные", is_enabled=True
        )
        step = RequestApprovalStepConfig.objects.create(
            payment_type_config=pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            payment_chat_id=None,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step, approver_user=self.approver)

        self.client.force_authenticate(self.admin)
        res = self.client.get("/api/requests/approval-config/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        cash_pt = next(pt for pt in res.data["payment_types"] if pt["payment_type"] == "Наличные")
        self.assertIsNone(cash_pt["steps"][0]["payment_chat_id"])

    # --- purpose-exception steps ---

    def test_put_saves_payment_chat_id_for_purpose_exception_step(self):
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
                                    "payment_chat_id": _STAGE_CHAT_ID,
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
        self.assertEqual(exc_step.payment_chat_id, _STAGE_CHAT_ID)

    def test_get_returns_payment_chat_id_for_purpose_exception_step(self):
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
            payment_chat_id=_STAGE_CHAT_ID,
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
        self.assertEqual(exc_steps[0]["payment_chat_id"], _STAGE_CHAT_ID)

    # --- round-trip: PUT then GET returns same value ---

    def test_round_trip_put_then_get_preserves_payment_chat_id(self):
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
                            "payment_chat_id": _STAGE_CHAT_ID,
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
        self.assertEqual(transfer_pt["steps"][0]["payment_chat_id"], _STAGE_CHAT_ID)
