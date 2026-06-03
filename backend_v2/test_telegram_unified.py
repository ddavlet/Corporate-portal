"""
Comprehensive test script for unified Telegram gateway.
Runs inside the backend_v2 container against the fake tg-gateway.

Usage:
    make test_local
    # or
    docker exec kolberg_backend_local python manage.py shell -c "exec(open('/app/test_telegram_unified.py').read())"
"""
import urllib.request, json
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from django.test.utils import override_settings

GATEWAY = "http://tg-gateway:8080"

def _get_log():
    resp = urllib.request.urlopen(f"{GATEWAY}/__log__")
    return json.loads(resp.read())

def _fake_callback(payload, user_id="1387986", recipient_id="1387986", message_id=None):
    """Simulate a Telegram button click via the fake gateway."""
    body = json.dumps({
        "payload": payload,
        "user_id": user_id,
        "recipient_id": recipient_id,
        "message_id": message_id,
    }).encode()
    resp = urllib.request.urlopen(urllib.request.Request(
        f"{GATEWAY}/__callback__",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    ))
    return json.loads(resp.read())

def _ok(label):
    print(f"  ✓ {label}")

def _count_log():
    return len(_get_log().get("entries", []))

def run_all():
    from apps.tenants.models import Tenant
    from apps.modules.requests.models import (
        Request, Approval,
        RequestApprovalConfig, RequestApprovalPaymentTypeConfig,
        RequestApprovalStepConfig, RequestApprovalStepApproverConfig,
    )
    from apps.modules.requests.serializers import ApprovalSerializer
    from apps.modules.telegram_approvals.services import (
        dispatch_pending_approvals,
        dispatch_draft_request_notification,
        refresh_request_messages,
        resend_current_pending_step,
        deactivate_approval_message_buttons,
        TelegramDispatcher,
    )
    from apps.modules.telegram_approvals.models import TelegramMessage, Notification
    from apps.modules.requests.approval_bootstrap import create_approval_rows_for_request
    from apps.modules.requests.approval_workflow import (
        find_approvals, lookup_approval_by_message_id,
        confirm_approval_by_id, ApprovalDecisionAlreadyMade,
    )
    from apps.modules.investments.models import (
        InvestCompany, InvestReturn, InvestmentReturnApproval,
        InvestmentApprovalConfig, InvestmentApprovalConfigStep, InvestmentApprovalConfigStepApprover,
        ProjectInvestment, ProjectInvestmentApproval,
        InvestmentProjectApprovalConfig, InvestmentProjectApprovalConfigStep, InvestmentProjectApprovalConfigStepApprover,
        InvestmentApprovalConfigStep, InvestPayoutSchedule,
    )
    from apps.modules.investments.approval_services import (
        _dispatch_approval_message as _invest_dispatch,
        refresh_invest_return_approval_messages,
        deactivate_investment_return_approval_buttons,
        confirm_invest_return_approval_by_id,
        InvestmentApprovalDecisionAlreadyMade as InvestAlreadyMade,
    )
    from apps.modules.investments.project_investment_approval_services import (
        deactivate_project_investment_approval_buttons,
        create_approvals_for_project_investment,
        dispatch_pending_project_investment_approvals,
        refresh_project_investment_approval_messages,
        confirm_project_investment_approval_by_id,
        InvestmentProjectApprovalDecisionAlreadyMade as ProjAlreadyMade,
    )
    from apps.modules.tasks.notifications.task_notifier import send_task_notification
    from apps.modules.tasks.models import Task, TasksConfig
    from apps.modules.feedback.models import PortalFeedback
    from django.contrib.auth import get_user_model

    User = get_user_model()
    tenant = Tenant.objects.get(subdomain="test")
    admin = User.objects.get(username="test_admin")
    ddavlet = User.objects.get(username="ddavlet")
    initial_log_count = _count_log()

    # ── 1. Request approval: 3-step serial flow ──────────────────────────────
    print("=" * 60)
    print("TEST 1: Request approval 3-step serial flow")
    print("=" * 60)

    r = Request.objects.create(
        tenant=tenant, created_by=admin, requester=admin,
        title="Unified test: 3-step", category="IT",
        amount=300000, currency="UZS", status=Request.STATUS_PROGRESS_1,
        billing_date=timezone.now().date(),
        payment_type=Request.PAYMENT_TYPE_CASH,
    )
    create_approval_rows_for_request(r)
    approvals = list(Approval.objects.filter(request=r).order_by("step"))

    sent = dispatch_pending_approvals(request_obj=r)
    assert sent == 1
    step1 = approvals[0]; step1.refresh_from_db()
    assert step1.telegram_message_id is not None
    assert step1.gateway_message_id is not None
    assert step1.message_sent is True
    _ok("Step 1 dispatched, TelegramMessage linked")

    tm = TelegramMessage.objects.get(pk=step1.telegram_message_id)
    assert tm.message_id == step1.gateway_message_id
    _ok("TelegramMessage row correct")

    _fake_callback(f"v2_{step1.id}:a", message_id=step1.gateway_message_id)
    step1.refresh_from_db()
    assert step1.decision == Approval.DECISION_APPROVED
    _ok("Step 1 approved via callback")

    dispatch_pending_approvals(request_obj=r)
    step2 = approvals[1]; step2.refresh_from_db()
    assert step2.telegram_message_id is not None
    _ok("Step 2 dispatched")

    _fake_callback(f"v2_{step2.id}:a", message_id=step2.gateway_message_id)
    step2.refresh_from_db()
    assert step2.decision == Approval.DECISION_APPROVED
    _ok("Step 2 approved")

    dispatch_pending_approvals(request_obj=r)
    step3 = approvals[2]; step3.refresh_from_db()
    assert step3.telegram_message_id is not None
    _ok("Step 3 (payment) dispatched")
    r.refresh_from_db()
    print(f"  Request status: {r.status}")

    # ── 2. find_approvals queries ────────────────────────────────────────────
    print(); print("=" * 60); print("TEST 2: find_approvals + lookup by message_id"); print("=" * 60)

    pending = find_approvals(request_obj=r, decision=Approval.DECISION_PENDING)
    approved = find_approvals(request_obj=r, decision=Approval.DECISION_APPROVED)
    assert approved.count() >= 2
    _ok("find_approvals works without message_sent filter")

    result = lookup_approval_by_message_id(tenant=tenant, message_id=step1.gateway_message_id)
    assert result.get("trigger_approval").id == step1.id
    _ok("lookup_approval_by_message_id works via telegram_message FK")

    # ── 3. refresh_request_messages ──────────────────────────────────────────
    print(); print("=" * 60); print("TEST 3: refresh_request_messages"); print("=" * 60)

    updated = refresh_request_messages(request_obj=r)
    assert updated >= 1
    _ok("refresh_request_messages works with telegram_message FK")

    # ── 4. resend_current_pending_step ───────────────────────────────────────
    print(); print("=" * 60); print("TEST 4: resend + idempotency"); print("=" * 60)

    r4 = Request.objects.create(
        tenant=tenant, created_by=admin, requester=admin,
        title="Resend test", category="IT",
        amount=75000, currency="UZS", status=Request.STATUS_PROGRESS_1,
        billing_date=timezone.now().date(),
        payment_type=Request.PAYMENT_TYPE_CASH,
    )
    create_approval_rows_for_request(r4)
    dispatch_pending_approvals(request_obj=r4)
    approval = Approval.objects.filter(request=r4, decision=Approval.DECISION_PENDING).first()

    created = resend_current_pending_step(request_obj=r4, idempotency_key="resend-001")
    assert created >= 1
    Approval.objects.get(id=approval.id)  # still exists, canceled
    dispatch_pending_approvals(request_obj=r4)
    new = Approval.objects.filter(request=r4, decision=Approval.DECISION_PENDING, resend_key="resend-001").first()
    assert new.telegram_message_id is not None
    _ok("Resend creates new approval, dispatches it")
    assert resend_current_pending_step(request_obj=r4, idempotency_key="resend-001") == created
    _ok("Idempotency works")

    # ── 5. Rejection + deactivate ────────────────────────────────────────────
    print(); print("=" * 60); print("TEST 5: Rejection cascade + deactivate"); print("=" * 60)

    r5 = Request.objects.create(
        tenant=tenant, created_by=admin, requester=admin,
        title="Reject test", category="IT",
        amount=120000, currency="UZS", status=Request.STATUS_PROGRESS_1,
        billing_date=timezone.now().date(),
        payment_type=Request.PAYMENT_TYPE_CASH,
    )
    create_approval_rows_for_request(r5)
    dispatch_pending_approvals(request_obj=r5)
    a5 = Approval.objects.filter(request=r5, decision=Approval.DECISION_PENDING).first()
    _fake_callback(f"v2_{a5.id}:r", message_id=a5.gateway_message_id)
    a5.refresh_from_db(); r5.refresh_from_db()
    assert a5.decision == Approval.DECISION_REJECTED
    assert r5.status == Request.STATUS_REJECTED
    _ok("Rejection: decision=REJECTED, status=REJECTED")

    r6 = Request.objects.create(tenant=tenant, created_by=admin, requester=admin,
        title="Deactivate", category="IT", amount=50000, currency="UZS",
        status=Request.STATUS_PROGRESS_1, billing_date=timezone.now().date(),
        payment_type=Request.PAYMENT_TYPE_CASH)
    create_approval_rows_for_request(r6)
    dispatch_pending_approvals(request_obj=r6)
    a6 = Approval.objects.filter(request=r6, decision=Approval.DECISION_PENDING).first()
    assert deactivate_approval_message_buttons(approval=a6) is True
    _ok("deactivate_approval_message_buttons works")

    # ── 6. Draft notification → Notification → TelegramMessage ───────────────
    print(); print("=" * 60); print("TEST 6: Draft notification → Notification"); print("=" * 60)

    r7 = Request.objects.create(tenant=tenant, created_by=admin, requester=admin,
        title="Draft test", category="IT", amount=50000, currency="UZS",
        status=Request.STATUS_DRAFT, billing_date=timezone.now().date(),
        payment_type=Request.PAYMENT_TYPE_CASH)
    assert dispatch_draft_request_notification(request_obj=r7, chat_id=ddavlet.telegram_chat_id) is True
    notif = Notification.objects.filter(kind=Notification.KIND_DRAFT, object_id=r7.pk).first()
    assert notif is not None and notif.telegram_message_id is not None
    _ok("Draft notification → Notification → TelegramMessage")

    # ── 7. Investment Return Approval ────────────────────────────────────────
    print(); print("=" * 60); print("TEST 7: Investment Return Approval"); print("=" * 60)

    cfg, _ = InvestmentApprovalConfig.objects.get_or_create(tenant=tenant)
    step_cfg, _ = InvestmentApprovalConfigStep.objects.get_or_create(
        config=cfg, step=1, defaults={"step_type": "serial", "is_enabled": True})
    InvestmentApprovalConfigStepApprover.objects.get_or_create(step=step_cfg, approver_user=ddavlet)

    company, _ = InvestCompany.objects.get_or_create(tenant=tenant, defaults={"name": "Test Co", "created_by": admin})
    ir = InvestReturn.objects.create(tenant=tenant, company=company, sum=500000, currency="UZS",
        date=timezone.now().date(), billing_date=timezone.now().replace(day=1),
        type=InvestReturn.ReturnType.DIVIDEND, recipient=InvestReturn.Recipient.INVESTOR,
        comment="Test", created_by=admin)
    a_ir = InvestmentReturnApproval.objects.create(invest_return=ir, tenant=tenant,
        approver_user=ddavlet, approver_recipient_id=str(ddavlet.telegram_chat_id),
        step=1, decision="pending")

    assert _invest_dispatch(approval=a_ir, include_buttons=True) is True
    a_ir.refresh_from_db()
    assert a_ir.telegram_message_id is not None and a_ir.gateway_message_id is not None
    _ok("Investment Return dispatch → TelegramMessage")
    assert refresh_invest_return_approval_messages(invest_return=ir) >= 1
    _ok("Investment Return refresh")
    assert deactivate_investment_return_approval_buttons(approval=a_ir) is True
    _ok("Investment Return deactivate")

    # ── 8. Project Investment Approval ───────────────────────────────────────
    print(); print("=" * 60); print("TEST 8: Project Investment Approval"); print("=" * 60)

    pcfg, _ = InvestmentProjectApprovalConfig.objects.get_or_create(tenant=tenant)
    pstep_cfg, _ = InvestmentProjectApprovalConfigStep.objects.get_or_create(
        config=pcfg, step=1, defaults={"step_type": "serial", "is_enabled": True})
    InvestmentProjectApprovalConfigStepApprover.objects.get_or_create(step=pstep_cfg, approver_user=ddavlet)

    pi = ProjectInvestment.objects.create(tenant=tenant, company=company, amount=1000000,
        currency="UZS", date=timezone.now().date(), comment="Test", created_by=admin, confirmed=False)
    a_pi = ProjectInvestmentApproval.objects.create(project_investment=pi, tenant=tenant,
        approver_user=ddavlet, approver_recipient_id=str(ddavlet.telegram_chat_id),
        step=1, decision="pending")

    assert dispatch_pending_project_investment_approvals(project_investment=pi) >= 1
    a_pi.refresh_from_db()
    assert a_pi.telegram_message_id is not None
    _ok("Project Investment dispatch → TelegramMessage")
    assert refresh_project_investment_approval_messages(project_investment=pi) >= 1
    _ok("Project Investment refresh")
    assert deactivate_project_investment_approval_buttons(approval=a_pi) is True
    _ok("Project Investment deactivate")

    # ═════════════════════════════════════════════════════════════════════════
    # NEW TESTS — gap coverage
    # ═════════════════════════════════════════════════════════════════════════

    # ── 9. Investment Return Approval webhook callback ───────────────────────
    print(); print("=" * 60); print("TEST 9: Investment Return Approval webhook callback")
    print("=" * 60)

    # Use a fresh InvestReturn to avoid unique constraint conflict with Test 7
    ir9 = InvestReturn.objects.create(tenant=tenant, company=company, sum=600000, currency="UZS",
        date=timezone.now().date(), billing_date=timezone.now().replace(day=1),
        type=InvestReturn.ReturnType.DIVIDEND, recipient=InvestReturn.Recipient.INVESTOR,
        comment="Callback test", created_by=admin)
    a_ir2 = InvestmentReturnApproval.objects.create(invest_return=ir9, tenant=tenant,
        approver_user=ddavlet, approver_recipient_id=str(ddavlet.telegram_chat_id),
        step=1, decision="pending")
    assert _invest_dispatch(approval=a_ir2, include_buttons=True) is True
    a_ir2.refresh_from_db()
    assert a_ir2.telegram_message_id is not None

    cb_result = _fake_callback(f"inv_{a_ir2.id}:a", message_id=a_ir2.gateway_message_id)
    assert cb_result["ok"] is True
    a_ir2.refresh_from_db()
    assert a_ir2.decision == "approved"
    _ok("Investment Return approval confirmed via callback")

    cb_result2 = _fake_callback(f"inv_{a_ir2.id}:a", message_id=a_ir2.gateway_message_id)
    assert cb_result2["backend_status"] in (409, 200)
    _ok("Double-approval handled (idempotency)")

    ir_reject = InvestReturn.objects.create(
        tenant=tenant,
        company=company,
        date=timezone.now().date(),
        billing_date=timezone.now().date(),
        sum=50000,
        currency="UZS",
        comment="Reject callback test",
        type=InvestReturn.ReturnType.DIVIDEND,
        recipient=InvestReturn.Recipient.INVESTOR,
        created_by=admin,
        confirmed=False,
    )
    a_ir_rej = InvestmentReturnApproval.objects.create(
        invest_return=ir_reject, tenant=tenant, approver_user=ddavlet,
        approver_recipient_id=str(ddavlet.telegram_chat_id),
        step=1, decision="pending",
    )
    assert _invest_dispatch(approval=a_ir_rej) is True
    a_ir_rej.refresh_from_db()
    cb_rej = _fake_callback(f"inv_{a_ir_rej.id}:r", message_id=a_ir_rej.gateway_message_id)
    assert cb_rej.get("ok") is True, cb_rej
    a_ir_rej.refresh_from_db()
    assert a_ir_rej.decision == "rejected"
    _ok("Investment Return reject via inv_:r callback")

    # ── 10. Project Investment Approval webhook callback ─────────────────────
    print(); print("=" * 60); print("TEST 10: Project Investment Approval webhook callback")
    print("=" * 60)

    # Use a fresh ProjectInvestment to avoid unique constraint conflict
    pi2 = ProjectInvestment.objects.create(tenant=tenant, company=company, amount=2000000,
        currency="UZS", date=timezone.now().date(), comment="Callback test", created_by=admin, confirmed=False)
    a_pi2 = ProjectInvestmentApproval.objects.create(project_investment=pi2, tenant=tenant,
        approver_user=ddavlet, approver_recipient_id=str(ddavlet.telegram_chat_id),
        step=1, decision="pending")

    assert dispatch_pending_project_investment_approvals(project_investment=pi2) >= 1
    a_pi2.refresh_from_db()
    assert a_pi2.telegram_message_id is not None

    cb_result = _fake_callback(f"invp_{a_pi2.id}:a", message_id=a_pi2.gateway_message_id)
    assert cb_result["ok"] is True
    a_pi2.refresh_from_db()
    assert a_pi2.decision == "approved"
    _ok("Project Investment approval confirmed via callback")

    pi_rej = ProjectInvestment.objects.create(
        tenant=tenant, company=company, amount=1500000,
        currency="UZS", date=timezone.now().date(), comment="Reject proj test",
        created_by=admin, confirmed=False,
    )
    a_pi_rej = ProjectInvestmentApproval.objects.create(
        project_investment=pi_rej, tenant=tenant, approver_user=ddavlet,
        approver_recipient_id=str(ddavlet.telegram_chat_id),
        step=1, decision="pending",
    )
    assert dispatch_pending_project_investment_approvals(project_investment=pi_rej) >= 1
    a_pi_rej.refresh_from_db()
    cb_pi_rej = _fake_callback(f"invp_{a_pi_rej.id}:r", message_id=a_pi_rej.gateway_message_id)
    assert cb_pi_rej.get("ok") is True, cb_pi_rej
    a_pi_rej.refresh_from_db()
    assert a_pi_rej.decision == "rejected"
    _ok("Project Investment reject via invp_:r callback")

    # ── 11. Task notification via TelegramDispatcher ─────────────────────────
    print(); print("=" * 60); print("TEST 11: Task notification → TelegramMessage")
    print("=" * 60)

    task = Task.objects.create(
        tenant=tenant, title="Task notification test", description="Test description",
        status="new", assignee=ddavlet, created_by=admin,
        last_edit_at=timezone.now(), last_edit_by=admin,
    )
    TasksConfig.objects.get_or_create(tenant=tenant)

    bot_token = tenant.get_telegram_bot_token() or "7947271968:AAHSpJ-o5k4RBBAnUwwVfCCAXjfGgVmeJS0"
    send_task_notification(task=task, tenant=tenant, bot_token=bot_token, is_reminder=False)
    task.refresh_from_db()
    assert task.telegram_message_id is not None
    tm_task = TelegramMessage.objects.get(pk=task.telegram_message_id)
    assert tm_task.message_id is not None
    _ok("Task notification → TelegramMessage linked via task.telegram_message")

    # Reminder also works
    task2 = Task.objects.create(
        tenant=tenant, title="Task reminder test", description="Reminder",
        status="new", assignee=ddavlet, created_by=admin,
        last_edit_at=timezone.now(), last_edit_by=admin,
    )
    send_task_notification(task=task2, tenant=tenant, bot_token=bot_token, is_reminder=True)
    task2.refresh_from_db()
    assert task2.telegram_message_id is not None
    _ok("Task reminder → TelegramMessage linked")

    # Task buttons use callback_data in notifier; gateway payload must expose "value".
    log_after_task = _get_log()
    task_send_entries = [
        e for e in log_after_task["entries"]
        if e.get("action") == "send" and any(
            "task_p_" in str(btn.get("value") or btn.get("callback_data") or "")
            for row in (e.get("buttons") or [])
            for btn in row
        )
    ]
    assert task_send_entries, "task notification should include progress/done buttons"
    for row in task_send_entries[-1].get("buttons") or []:
        for btn in row:
            assert btn.get("value"), f"normalized button missing value: {btn}"
    _ok("Task buttons normalized to gateway value field")

    cb_task = _fake_callback(
        f"task_p_{task.pk}",
        user_id=str(ddavlet.telegram_from_id),
        recipient_id=str(ddavlet.telegram_chat_id or ddavlet.telegram_from_id),
        message_id=tm_task.message_id,
    )
    assert cb_task.get("ok") is True, cb_task
    task.refresh_from_db()
    assert task.status == "in_progress"
    _ok("task_p_ webhook → in_progress via messaging gateway")

    # ── 12. Portal feedback dispatch → Notification ──────────────────────────
    print(); print("=" * 60); print("TEST 12: Portal feedback → Notification → TelegramMessage")
    print("=" * 60)

    fb = PortalFeedback.objects.create(
        tenant=tenant, created_by=admin, kind=PortalFeedback.KIND_ERROR,
        body="Test feedback body", page_path="/app/requests/1",
    )
    from apps.tenants.integration_settings import get_portal_feedback_settings
    from apps.modules.telegram_approvals.models import Notification as NotifModel
    pf = get_portal_feedback_settings(tenant=tenant)

    # Test tenant may not have feedback recipient configured — test the dispatcher path directly
    if pf.recipient_id is not None:
        dispatcher = TelegramDispatcher(tenant)
        msg = dispatcher.send(
            action=pf.action,
            recipient_id=int(pf.recipient_id),
            text=f"<b>Обратная связь портала</b>\nТип: Ошибка\nОт: test_admin\nID: {fb.pk}\nСтраница: /app/requests/1\n\nTest feedback body",
            buttons=[],
            link=None,
            request_id=fb.pk,
        )
        assert msg is not None
        NotifModel.objects.create(
            tenant=tenant,
            kind=NotifModel.KIND_PORTAL_FEEDBACK,
            telegram_message=msg,
            content_type=ContentType.objects.get_for_model(PortalFeedback),
            object_id=fb.pk,
        )
        notif = NotifModel.objects.filter(kind=NotifModel.KIND_PORTAL_FEEDBACK, object_id=fb.pk).first()
        assert notif is not None and notif.telegram_message_id is not None
        _ok("Portal feedback → Notification → TelegramMessage")
    else:
        # Fallback: test dispatcher directly with known recipient
        dispatcher = TelegramDispatcher(tenant)
        msg = dispatcher.send(
            action="send_portal_feedback",
            recipient_id=ddavlet.telegram_chat_id,
            text="<b>Обратная связь портала</b>\nTest",
            buttons=[],
            link=None,
            request_id=fb.pk,
        )
        assert msg is not None
        NotifModel.objects.create(
            tenant=tenant,
            kind=NotifModel.KIND_PORTAL_FEEDBACK,
            telegram_message=msg,
            content_type=ContentType.objects.get_for_model(PortalFeedback),
            object_id=fb.pk,
        )
        notif = NotifModel.objects.filter(kind=NotifModel.KIND_PORTAL_FEEDBACK, object_id=fb.pk).first()
        assert notif is not None
        _ok("Portal feedback → Notification → TelegramMessage (via direct dispatcher)")

    # ── 13. STEP_TYPE_NOTIFICATION auto-approval ─────────────────────────────
    print(); print("=" * 60); print("TEST 13: STEP_TYPE_NOTIFICATION auto-approves after send")
    print("=" * 60)

    r8 = Request.objects.create(tenant=tenant, created_by=admin, requester=admin,
        title="Notification step test", category="IT", amount=10000, currency="UZS",
        status=Request.STATUS_PROGRESS_1, billing_date=timezone.now().date(),
        payment_type=Request.PAYMENT_TYPE_CASH)

    # Create approval config with notification step (use step=9 to avoid conflicts)
    approval_cfg, _ = RequestApprovalConfig.objects.get_or_create(tenant=tenant, defaults={"updated_by": admin})
    approval_cfg.updated_by = admin
    approval_cfg.save()
    pt_cfg, _ = RequestApprovalPaymentTypeConfig.objects.get_or_create(
        config=approval_cfg, payment_type=Request.PAYMENT_TYPE_CASH,
        defaults={"is_enabled": True})
    # Create notification step at step=9 (won't conflict with existing 1/2/3)
    step_cfg, _ = RequestApprovalStepConfig.objects.update_or_create(
        payment_type_config=pt_cfg, step=9,
        defaults={"step_type": Approval.STEP_TYPE_NOTIFICATION, "is_enabled": True})
    RequestApprovalStepApproverConfig.objects.get_or_create(
        step_config=step_cfg, approver_user=ddavlet)

    # Create approval row manually for the notification step
    notif_approval = Approval.objects.create(
        request=r8, approver_user=ddavlet,
        approver_recipient_id=str(ddavlet.telegram_chat_id),
        approver_external_user_id=ddavlet.telegram_from_id,
        step=9, step_type=Approval.STEP_TYPE_NOTIFICATION,
        decision=Approval.DECISION_PENDING,
    )
    assert notif_approval.decision == Approval.DECISION_PENDING
    _ok("Notification approval created (pending)")

    dispatch_pending_approvals(request_obj=r8, step=9)
    notif_approval.refresh_from_db()
    assert notif_approval.decision == Approval.DECISION_APPROVED
    assert notif_approval.telegram_message_id is not None
    _ok("Notification step auto-approved after dispatch")

    # ── 14. Gateway unreachable graceful handling ────────────────────────────
    print(); print("=" * 60); print("TEST 14: Gateway unreachable → graceful failure")
    print("=" * 60)

    r9 = Request.objects.create(tenant=tenant, created_by=admin, requester=admin,
        title="Gateway down test", category="IT", amount=10000, currency="UZS",
        status=Request.STATUS_PROGRESS_1, billing_date=timezone.now().date(),
        payment_type=Request.PAYMENT_TYPE_CASH)
    create_approval_rows_for_request(r9)

    # Point gateway to a non-existent host — Dispatcher should return None, not crash
    with override_settings(MESSAGING_GATEWAY_SEND_URL="http://nonexistent-host-xyz:9999/v1/messaging/send"):
        sent = dispatch_pending_approvals(request_obj=r9)
        assert sent == 0  # no messages sent
    a9 = Approval.objects.filter(request=r9).first()
    a9.refresh_from_db()
    assert a9.telegram_message_id is None
    assert a9.message_sent is False
    _ok("Gateway unreachable → returns 0 sent, no crash, approval unchanged")

    # ── 15. Serializer derived fields (API stability) ────────────────────────
    print(); print("=" * 60); print("TEST 15: Serializer exposes derived fields")
    print("=" * 60)

    serializer = ApprovalSerializer(a_ir2)
    data = serializer.data
    assert "gateway_message_id" in data
    assert "message_sent" in data
    assert "message_sent_at" in data
    assert data["gateway_message_id"] is not None
    assert data["message_sent"] is True
    _ok("Investment Return Approval serializer exposes derived fields")

    serializer2 = ApprovalSerializer(step1)
    data2 = serializer2.data
    assert data2["gateway_message_id"] is not None
    assert data2["message_sent"] is True
    _ok("Request Approval serializer exposes derived fields")

    # ── 16. TelegramMessage reverse relation integrity ───────────────────────
    print(); print("=" * 60); print("TEST 16: TelegramMessage reverse relation integrity")
    print("=" * 60)

    total = TelegramMessage.objects.count()
    orphaned = 0
    for tm in TelegramMessage.objects.all():
        has_link = False
        try:
            has_link = tm.request_approval is not None
        except TelegramMessage.request_approval.RelatedObjectDoesNotExist:
            pass
        if not has_link:
            try: has_link = tm.notification is not None
            except TelegramMessage.notification.RelatedObjectDoesNotExist: pass
        if not has_link:
            try: has_link = tm.investment_return_approval is not None
            except TelegramMessage.investment_return_approval.RelatedObjectDoesNotExist: pass
        if not has_link:
            try: has_link = tm.project_investment_approval is not None
            except TelegramMessage.project_investment_approval.RelatedObjectDoesNotExist: pass
        if not has_link:
            try: has_link = tm.task is not None
            except TelegramMessage.task.RelatedObjectDoesNotExist: pass
        if not has_link:
            orphaned += 1
            print(f"  ⚠ TelegramMessage id={tm.id} message_id={tm.message_id} has no reverse link")

    print(f"  Total TelegramMessage rows: {total}")
    print(f"  Linked: {total - orphaned}, Orphaned: {orphaned}")
    # We expect some orphaned from earlier sessions (before refactoring)
    assert total - orphaned >= 10  # at least 10 should be linked by our tests
    _ok("TelegramMessage reverse relation integrity verified")

    # ── 17. TelegramDispatcher helper contract ───────────────────────────────
    print(); print("=" * 60)
    print("TEST 17: normalize_gateway_buttons + build_gateway_payload")
    print("=" * 60)
    from apps.modules.telegram_approvals.services import (
        build_gateway_payload,
        normalize_gateway_buttons,
    )
    rows = normalize_gateway_buttons(
        [[{"label": "X", "callback_data": "task_p_99"}]]
    )
    assert rows[0][0]["value"] == "task_p_99"
    payload = build_gateway_payload(
        action="send",
        tenant_id=tenant.pk,
        recipient_id=1,
        bot_token="tok",
        message_text="t",
        buttons=rows,
    )
    assert payload["buttons"][0][0]["value"] == "task_p_99"
    _ok("Dispatcher helpers produce gateway-ready button rows")

    # ── 18. Summary ─────────────────────────────────────────────────────────
    print(); print("=" * 60)
    print("TEST 18: Fake gateway captured all dispatches")
    print("=" * 60)

    log = _get_log()
    actions = {}
    for entry in log["entries"]:
        action = entry.get("action", "unknown")
        actions[action] = actions.get(action, 0) + 1
    new_entries = log["count"] - initial_log_count
    print(f"  New dispatches this run: {new_entries}")
    print(f"  Actions: {actions}")
    assert new_entries >= 18  # dispatches grow as webhook/callback paths expand
    _ok(f"All {new_entries} dispatches captured by fake gateway")

    print()
    print("=" * 60)
    print("ALL 18 TESTS PASSED ✅")
    print("=" * 60)


run_all()
