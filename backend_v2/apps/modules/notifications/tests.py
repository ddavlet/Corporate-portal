from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.modules.investments.models import (
    InvestmentApprovalConfigStep,
    InvestmentProjectApprovalConfigStep,
    InvestmentReturnApproval,
    InvestReturn,
    ProjectInvestment,
    ProjectInvestmentApproval,
)
from apps.modules.notifications.services import collect_action_items, with_company_param
from apps.modules.requests.models import Approval, Request
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()

URL = "/api/notifications/action-items/"


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class ActionItemsApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme-notif", is_active=True)
        self.host = "acme-notif.example.com"
        self.other_tenant = Tenant.objects.create(name="Beta", subdomain="beta-notif", is_active=True)
        self.other_host = "beta-notif.example.com"
        self.user = User.objects.create_user(username="notif-user", password="x")
        self.colleague = User.objects.create_user(username="notif-colleague", password="x")
        self.other_user = User.objects.create_user(username="notif-other", password="x")
        for user in (self.user, self.colleague):
            TenantMembership.objects.create(tenant=self.tenant, user=user, is_active=True)
        TenantMembership.objects.create(tenant=self.other_tenant, user=self.other_user, is_active=True)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="investments", is_enabled=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.user, role=TenantUserRole.ROLE_INVESTOR)
        self.client.force_authenticate(self.user)

    # --- fixtures -------------------------------------------------------------------

    def _request(self, *, status, tenant=None, created_at=None):
        return Request.all_objects.create(
            tenant=tenant or self.tenant,
            created_by=self.user,
            requester=self.user,
            title="Закупка",
            amount=Decimal("1500.50"),
            currency=Request.CURRENCY_UZS,
            payment_type=Request.PAYMENT_TYPE_CASH,
            status=status,
            billing_date=timezone.localdate(),
            created_at=created_at or timezone.now(),
        )

    def _request_approval(self, request_obj, *, step, step_type=Approval.STEP_TYPE_SERIAL, user=None):
        return Approval.objects.create(
            request=request_obj,
            approver_user=user or self.user,
            step=step,
            step_type=step_type,
        )

    def _invest_return(self, *, tenant=None):
        return InvestReturn.objects.create(
            tenant=tenant or self.tenant,
            date=date(2026, 11, 1),
            billing_date=date(2026, 11, 1),
            sum=Decimal("1200.00"),
            currency="USD",
            type=InvestReturn.ReturnType.DIVIDEND,
            recipient=InvestReturn.Recipient.INVESTOR,
            created_by=self.user,
        )

    def _return_approval(self, invest_return, *, step, user=None, decision=None):
        return InvestmentReturnApproval.objects.create(
            tenant=invest_return.tenant,
            invest_return=invest_return,
            step=step,
            step_type=InvestmentApprovalConfigStep.STEP_TYPE_SERIAL,
            approver_user=user or self.user,
            decision=decision or InvestmentReturnApproval.DECISION_PENDING,
        )

    def _project_investment(self):
        return ProjectInvestment.objects.create(
            tenant=self.tenant,
            date=date(2026, 11, 1),
            amount=Decimal("5000.00"),
            currency="USD",
            funding_method=ProjectInvestment.FundingMethod.CASH,
            created_by=self.user,
        )

    def _project_approval(self, investment, *, step, user=None, decision=None):
        return ProjectInvestmentApproval.objects.create(
            tenant=investment.tenant,
            project_investment=investment,
            step=step,
            step_type=InvestmentProjectApprovalConfigStep.STEP_TYPE_SERIAL,
            approver_user=user or self.user,
            decision=decision or ProjectInvestmentApproval.DECISION_PENDING,
        )

    def _get(self, host=None):
        return self.client.get(URL, HTTP_HOST=host or self.host)

    def _keys(self, response):
        return [(item["kind"], item["id"]) for item in response.json()["items"]]

    # --- request rule (p.6–10) ------------------------------------------------------

    def test_request_rule_end_to_end(self):
        active = self._request(status=Request.STATUS_PROGRESS_2)  # p.6
        self._request_approval(active, step=2)
        future = self._request(status=Request.STATUS_PROGRESS_2)  # p.7
        self._request_approval(future, step=2, user=self.colleague)
        self._request_approval(future, step=3)
        payment = self._request(status=Request.STATUS_APPROVED)  # p.8
        self._request_approval(payment, step=2, step_type=Approval.STEP_TYPE_PAYMENT)
        notification = self._request(status=Request.STATUS_PROGRESS_1)  # p.9
        self._request_approval(notification, step=1, step_type=Approval.STEP_TYPE_NOTIFICATION)
        for status in (Request.STATUS_REJECTED, Request.STATUS_DELETED):  # p.10
            self._request_approval(self._request(status=status), step=1)

        res = self._get()

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["count"], 2)
        self.assertEqual(sorted(self._keys(res)), sorted([("request", active.id), ("request", payment.id)]))
        item = next(i for i in body["items"] if i["id"] == active.id)
        self.assertEqual(item["amount"], "1500.50")
        self.assertEqual(item["step"], 2)
        self.assertEqual(item["step_type"], "serial")
        self.assertEqual(item["link"], f"/requests/{active.id}")
        self.assertEqual(
            set(item),
            {
                "kind",
                "id",
                "approval_id",
                "step",
                "step_type",
                "title",
                "amount",
                "currency",
                "type_code",
                "type_label",
                "created_at",
                "link",
            },
        )

    def test_payment_step_disappears_after_payed(self):  # p.8
        req = self._request(status=Request.STATUS_APPROVED)
        self._request_approval(req, step=2, step_type=Approval.STEP_TYPE_PAYMENT)
        self.assertEqual(self._get().json()["count"], 1)

        req.status = Request.STATUS_PAYED
        req.save(update_fields=["status"])

        self.assertEqual(self._get().json(), {"count": 0, "items": []})

    # --- investments (p.11) ---------------------------------------------------------

    def test_investment_current_step_end_to_end(self):
        current = self._invest_return()
        self._return_approval(current, step=1)
        waiting = self._invest_return()
        self._return_approval(waiting, step=1, user=self.colleague)
        self._return_approval(waiting, step=2)
        blocked = self._invest_return()
        self._return_approval(blocked, step=1, user=self.colleague, decision=InvestmentReturnApproval.DECISION_REJECTED)
        self._return_approval(blocked, step=1)
        project = self._project_investment()
        self._project_approval(project, step=1)
        blocked_project = self._project_investment()
        self._project_approval(
            blocked_project, step=1, user=self.colleague, decision=ProjectInvestmentApproval.DECISION_REJECTED
        )
        self._project_approval(blocked_project, step=1)

        res = self._get()

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["count"], 2)
        self.assertEqual(
            sorted(self._keys(res)),
            sorted([("invest_return", current.id), ("project_investment", project.id)]),
        )

    def test_items_sorted_newest_first(self):
        old_request = self._request(status=Request.STATUS_PROGRESS_1, created_at=timezone.now() - timedelta(days=3))
        self._request_approval(old_request, step=1)
        new_return = self._invest_return()
        self._return_approval(new_return, step=1)

        self.assertEqual(self._keys(self._get()), [("invest_return", new_return.id), ("request", old_request.id)])

    # --- access (p.12–14) -----------------------------------------------------------

    def test_user_of_other_tenant_gets_403(self):  # p.12
        foreign = self._request(status=Request.STATUS_PROGRESS_1, tenant=self.other_tenant)
        self._request_approval(foreign, step=1, user=self.other_user)

        res = self._get(host=self.other_host)

        self.assertEqual(res.status_code, 403)

    def test_other_tenant_data_is_not_visible(self):  # p.12
        foreign = self._request(status=Request.STATUS_PROGRESS_1, tenant=self.other_tenant)
        self._request_approval(foreign, step=1)
        foreign_return = self._invest_return(tenant=self.other_tenant)
        self._return_approval(foreign_return, step=1)

        self.assertEqual(self._get().json(), {"count": 0, "items": []})

    def test_inactive_membership_gets_403(self):
        TenantMembership.objects.filter(tenant=self.tenant, user=self.user).update(is_active=False)

        self.assertEqual(self._get().status_code, 403)

    def test_investments_module_disabled_returns_only_requests(self):  # p.13
        TenantModuleConfig.objects.filter(tenant=self.tenant, module_key="investments").update(is_enabled=False)
        req = self._request(status=Request.STATUS_PROGRESS_1)
        self._request_approval(req, step=1)
        self._return_approval(self._invest_return(), step=1)

        res = self._get()

        self.assertEqual(res.status_code, 200)
        self.assertEqual(self._keys(res), [("request", req.id)])

    def test_without_investments_module_config_returns_only_requests(self):  # p.13
        TenantModuleConfig.objects.filter(tenant=self.tenant, module_key="investments").delete()
        self._return_approval(self._invest_return(), step=1)

        res = self._get()

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"count": 0, "items": []})

    def test_director_without_investments_role_gets_only_requests(self):
        # /investments is guarded by HasEffectiveModuleAccess (admin/investor only):
        # a link there would end in 403 for a director approver.
        director = User.objects.create_user(username="notif-director", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=director, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=director, role=TenantUserRole.ROLE_DIRECTOR)
        req = self._request(status=Request.STATUS_PROGRESS_1)
        self._request_approval(req, step=1, user=director)
        self._return_approval(self._invest_return(), step=1, user=director)
        self._project_approval(self._project_investment(), step=1, user=director)
        self.client.force_authenticate(director)

        res = self._get()

        self.assertEqual(res.status_code, 200)
        self.assertEqual(self._keys(res), [("request", req.id)])

    def test_investments_admin_role_gets_investment_items(self):
        admin = User.objects.create_user(username="notif-admin", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=admin, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=admin, role=TenantUserRole.ROLE_ADMIN)
        invest_return = self._invest_return()
        self._return_approval(invest_return, step=1, user=admin)
        self.client.force_authenticate(admin)

        self.assertEqual(self._keys(self._get()), [("invest_return", invest_return.id)])

    def test_unknown_tenant_host_gets_404(self):  # p.12
        res = self.client.get(URL, HTTP_HOST="nobody-notif.example.com")

        self.assertEqual(res.status_code, 404)

    def test_anonymous_gets_401(self):  # p.14
        self.client.force_authenticate(None)

        self.assertEqual(self._get().status_code, 401)

    # --- queries --------------------------------------------------------------------

    def test_collect_action_items_query_count_does_not_grow_with_items(self):
        for _ in range(3):
            self._request_approval(self._request(status=Request.STATUS_PROGRESS_1), step=1)
            self._return_approval(self._invest_return(), step=1)
            self._project_approval(self._project_investment(), step=1)

        # module switch, membership, role (investments access) + one query per provider.
        with self.assertNumQueries(6):
            items = collect_action_items(tenant=self.tenant, user=self.user)

        self.assertEqual(len(items), 9)

    # --- resilience -----------------------------------------------------------------

    def test_failing_provider_is_logged_and_skipped(self):
        self._return_approval(self._invest_return(), step=1)
        with patch(
            "apps.modules.notifications.services.list_request_action_items",
            side_effect=RuntimeError("boom"),
        ), self.assertLogs("apps.modules.notifications.services", level="ERROR") as logs:
            res = self._get()

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["count"], 1)
        self.assertEqual(res.json()["items"][0]["kind"], "invest_return")
        self.assertTrue(any("action_items provider failed" in line for line in logs.output))


@override_settings(
    BASE_DOMAIN="example.com", PORTAL_SHARED_HOST="app.example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"]
)
class AllActionItemsApiTests(APITestCase):
    URL = "/api/notifications/action-items/all/"

    def setUp(self):
        self.user = User.objects.create_user(username="all-notif-user", password="x")
        self.acme = Tenant.objects.create(name="Acme", subdomain="acme-all", is_active=True)
        self.beta = Tenant.objects.create(name="Beta", subdomain="beta-all", is_active=True)
        self.gamma = Tenant.objects.create(name="Gamma", subdomain="gamma-all", is_active=True)
        TenantMembership.objects.create(tenant=self.acme, user=self.user, is_active=True)
        TenantMembership.objects.create(tenant=self.beta, user=self.user, is_active=True)
        TenantMembership.objects.create(tenant=self.gamma, user=self.user, is_active=False)
        TenantModuleConfig.objects.create(tenant=self.acme, module_key="investments", is_enabled=True)
        TenantUserRole.objects.create(tenant=self.acme, user=self.user, role=TenantUserRole.ROLE_INVESTOR)
        self.client.force_authenticate(self.user)

    def _pending_request(self, tenant):
        req = Request.all_objects.create(
            tenant=tenant,
            created_by=self.user,
            requester=self.user,
            title="Закупка",
            amount=Decimal("10.00"),
            currency=Request.CURRENCY_UZS,
            payment_type=Request.PAYMENT_TYPE_CASH,
            status=Request.STATUS_PROGRESS_1,
            billing_date=timezone.localdate(),
        )
        Approval.objects.create(request=req, approver_user=self.user, step=1, step_type=Approval.STEP_TYPE_SERIAL)
        return req

    def _pending_return(self, tenant):
        invest_return = InvestReturn.objects.create(
            tenant=tenant,
            date=date(2026, 11, 1),
            billing_date=date(2026, 11, 1),
            sum=Decimal("1200.00"),
            currency="USD",
            type=InvestReturn.ReturnType.DIVIDEND,
            recipient=InvestReturn.Recipient.INVESTOR,
            created_by=self.user,
        )
        InvestmentReturnApproval.objects.create(
            tenant=tenant,
            invest_return=invest_return,
            step=1,
            step_type=InvestmentApprovalConfigStep.STEP_TYPE_SERIAL,
            approver_user=self.user,
            decision=InvestmentReturnApproval.DECISION_PENDING,
        )
        return invest_return

    def test_items_of_all_active_companies_with_tenant_and_company_link(self):  # crit. 10
        acme_request = self._pending_request(self.acme)
        acme_return = self._pending_return(self.acme)
        beta_request = self._pending_request(self.beta)
        self._pending_request(self.gamma)  # inactive membership: not shown

        res = self.client.get(self.URL, HTTP_HOST="app.example.com")

        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual(body["count"], 3)
        by_key = {(item["kind"], item["id"]): item for item in body["items"]}
        self.assertEqual(
            set(by_key),
            {("request", acme_request.id), ("invest_return", acme_return.id), ("request", beta_request.id)},
        )
        self.assertEqual(by_key[("request", beta_request.id)]["tenant"], {"subdomain": "beta-all", "name": "Beta"})
        self.assertEqual(by_key[("request", acme_request.id)]["link"], f"/requests/{acme_request.id}?company=acme-all")
        self.assertEqual(
            by_key[("invest_return", acme_return.id)]["link"],
            f"/investments?tab=returns&open={acme_return.id}&company=acme-all",
        )

    def test_failing_company_is_logged_and_skipped(self):
        self._pending_request(self.acme)
        beta_request = self._pending_request(self.beta)
        real_collect = collect_action_items

        def fake_collect(*, tenant, user):
            if tenant == self.acme:
                raise RuntimeError("boom")
            return real_collect(tenant=tenant, user=user)

        with patch(
            "apps.modules.notifications.services.collect_action_items", side_effect=fake_collect
        ), self.assertLogs("apps.modules.notifications.services", level="ERROR") as logs:
            res = self.client.get(self.URL, HTTP_HOST="app.example.com")

        self.assertEqual(res.status_code, 200)
        self.assertEqual([(i["kind"], i["id"]) for i in res.json()["items"]], [("request", beta_request.id)])
        self.assertTrue(any("action_items tenant failed" in line for line in logs.output))

    def test_works_on_tenant_subdomain_too(self):
        self._pending_request(self.beta)

        res = self.client.get(self.URL, HTTP_HOST="acme-all.example.com")

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["count"], 1)

    def test_anonymous_gets_401(self):
        self.client.force_authenticate(None)

        self.assertEqual(self.client.get(self.URL, HTTP_HOST="app.example.com").status_code, 401)

    def test_with_company_param(self):
        self.assertEqual(with_company_param("/requests/5", "acme"), "/requests/5?company=acme")
        self.assertEqual(with_company_param("/investments?tab=returns&open=1", "acme"), "/investments?tab=returns&open=1&company=acme")
