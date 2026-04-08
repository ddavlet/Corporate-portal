
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modules.bank_expenses.models import BankExpense, BankRevenue
from apps.modules.payroll.models import PayrollLine
from apps.modules.cashier.models import CashExpense, CashRevenue
from apps.modules.corporate_card.models import CardExpense, CardRevenue
from apps.modules.notes.models import Note
from apps.modules.requests.models import Approval, Request
from apps.modules.vendors.models import Vendor
from apps.modules.n8n_integration.authentication import N8nIntegrationAuthentication
from apps.modules.n8n_integration.serializers import (
    N8nApprovalImportSerializer,
    N8nBankExpenseImportSerializer,
    N8nBankRevenueImportSerializer,
    N8nCardExpenseImportSerializer,
    N8nCardRevenueImportSerializer,
    N8nCashExpenseImportSerializer,
    N8nCashRevenueImportSerializer,
    N8nNoteImportSerializer,
    N8nPayrollLineImportSerializer,
    N8nRequestImportSerializer,
    N8nVendorImportSerializer,
)
from apps.tenants.permissions import IsTenantAdmin

User = get_user_model()


def _system_user():
    return User.objects.filter(pk=1).first()


def _n8n_upsert(request, *, serializer_class, get_instance, other_tenant_conflict, build_create_kwargs):
    su = _system_user()
    if su is None:
        return Response({"detail": "System user (pk=1) is missing."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    data = request.data
    pk = data.get("id")
    if pk not in (None, ""):
        try:
            pk = int(pk)
        except (TypeError, ValueError):
            return Response({"id": ["Must be an integer."]}, status=status.HTTP_400_BAD_REQUEST)
    else:
        pk = None

    # Create without client PK when `id` is not provided.
    if pk is None:
        ser = serializer_class(data=data, context={"request": request})
        ser.is_valid(raise_exception=True)
        try:
            ser.save(**build_create_kwargs(request, su))
        except IntegrityError:
            return Response({"detail": "Could not create with this payload."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ser.data, status=status.HTTP_201_CREATED)

    instance = get_instance(pk)
    ctx = {"request": request}

    if instance:
        ser = serializer_class(instance=instance, data=data, partial=True, context=ctx)
        ser.is_valid(raise_exception=True)
        try:
            ser.save()
        except IntegrityError as exc:
            return Response({"detail": "Could not update with this payload."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ser.data, status=status.HTTP_200_OK)

    if other_tenant_conflict(pk):
        return Response({"id": ["This ID already exists in another tenant."]}, status=status.HTTP_400_BAD_REQUEST)

    ser = serializer_class(data=data, context=ctx)
    ser.is_valid(raise_exception=True)
    try:
        ser.save(id=pk, **build_create_kwargs(request, su))
    except IntegrityError as exc:
        return Response({"detail": "Could not create with this ID."}, status=status.HTTP_400_BAD_REQUEST)
    return Response(ser.data, status=status.HTTP_201_CREATED)


class _N8nBaseView(APIView):
    authentication_classes = [N8nIntegrationAuthentication]
    permission_classes = [IsAuthenticated, IsTenantAdmin]


class N8nVendorUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant
        raw_acc = request.data.get("account_number", request.data.get("account_no"))
        account_no = (str(raw_acc).strip() if raw_acc is not None else "")

        # For vendor imports, support upsert-by-account when client id is omitted.
        if request.data.get("id") in (None, "") and account_no:
            existing = None
            existing = Vendor.objects.filter(tenant=tenant, account_number=account_no).first()
            if existing is not None:
                ser = N8nVendorImportSerializer(
                    instance=existing,
                    data=request.data,
                    partial=True,
                    context={"request": request},
                )
                ser.is_valid(raise_exception=True)
                try:
                    ser.save()
                except IntegrityError:
                    return Response(
                        {"detail": "Could not update with this payload."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                return Response(ser.data, status=status.HTTP_200_OK)

        def get_instance(pk):
            return Vendor.objects.filter(pk=pk, tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = Vendor.objects.filter(pk=pk).first()
            return o is not None and o.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {"tenant": req.tenant, "created_by": su}

        return _n8n_upsert(
            request,
            serializer_class=N8nVendorImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


class N8nRequestUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant

        def get_instance(pk):
            return Request.objects.filter(pk=pk, tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = Request.objects.filter(pk=pk).first()
            return o is not None and o.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {"tenant": req.tenant, "created_by": su}

        return _n8n_upsert(
            request,
            serializer_class=N8nRequestImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


class N8nApprovalUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant

        def get_instance(pk):
            return Approval.objects.filter(pk=pk, request__tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = Approval.objects.filter(pk=pk).select_related("request").first()
            return o is not None and o.request.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {}

        return _n8n_upsert(
            request,
            serializer_class=N8nApprovalImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


class N8nCashExpenseUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant

        def get_instance(pk):
            return CashExpense.objects.filter(pk=pk, tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = CashExpense.objects.filter(pk=pk).first()
            return o is not None and o.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {"tenant": req.tenant, "created_by": su}

        return _n8n_upsert(
            request,
            serializer_class=N8nCashExpenseImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


class N8nCashRevenueUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant
        su = _system_user()
        if su is None:
            return Response({"detail": "System user (pk=1) is missing."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        payload = dict(request.data)
        raw_id = payload.get("id")
        raw_pk = payload.get("pk")
        # External source format support:
        # - pk: numeric DB id for upsert
        # - id: business external identifier
        if raw_id not in (None, "") and raw_pk not in (None, ""):
            try:
                payload["id"] = int(raw_pk)
                payload.setdefault("external_id", str(raw_id).strip())
                raw_id = payload.get("id")
            except (TypeError, ValueError):
                pass

        if raw_id not in (None, ""):
            try:
                int(raw_id)
            except (TypeError, ValueError):
                external_id = str(raw_id).strip()
                if not external_id:
                    return Response({"id": ["Must be an integer."]}, status=status.HTTP_400_BAD_REQUEST)
                payload.pop("id", None)
                payload.setdefault("external_id", external_id)

                existing = CashRevenue.objects.filter(tenant=tenant, external_id=external_id).first()
                if existing is not None:
                    ser = N8nCashRevenueImportSerializer(
                        instance=existing,
                        data=payload,
                        partial=True,
                        context={"request": request},
                    )
                    ser.is_valid(raise_exception=True)
                    try:
                        ser.save()
                    except IntegrityError:
                        return Response({"detail": "Could not update with this payload."}, status=status.HTTP_400_BAD_REQUEST)
                    return Response(ser.data, status=status.HTTP_200_OK)

                ser = N8nCashRevenueImportSerializer(data=payload, context={"request": request})
                ser.is_valid(raise_exception=True)
                try:
                    ser.save(tenant=request.tenant, created_by=su)
                except IntegrityError:
                    return Response({"detail": "Could not create with this payload."}, status=status.HTTP_400_BAD_REQUEST)
                return Response(ser.data, status=status.HTTP_201_CREATED)

        def get_instance(pk):
            return CashRevenue.objects.filter(pk=pk, tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = CashRevenue.objects.filter(pk=pk).first()
            return o is not None and o.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {"tenant": req.tenant, "created_by": su}

        class _Req:
            data = payload
            tenant = request.tenant
            META = request.META
            method = request.method
            user = request.user
            path = request.path

        return _n8n_upsert(
            _Req(),
            serializer_class=N8nCashRevenueImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


class N8nBankExpenseUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant

        def get_instance(pk):
            return BankExpense.objects.filter(pk=pk, tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = BankExpense.objects.filter(pk=pk).first()
            return o is not None and o.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {"tenant": req.tenant, "created_by": su}

        return _n8n_upsert(
            request,
            serializer_class=N8nBankExpenseImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


class N8nBankRevenueUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant

        def get_instance(pk):
            return BankRevenue.objects.filter(pk=pk, tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = BankRevenue.objects.filter(pk=pk).first()
            return o is not None and o.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {"tenant": req.tenant, "created_by": su}

        return _n8n_upsert(
            request,
            serializer_class=N8nBankRevenueImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


class N8nCardExpenseUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant

        def get_instance(pk):
            return CardExpense.objects.filter(pk=pk, tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = CardExpense.objects.filter(pk=pk).first()
            return o is not None and o.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {"tenant": req.tenant, "created_by": su}

        return _n8n_upsert(
            request,
            serializer_class=N8nCardExpenseImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


class N8nCardRevenueUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant

        def get_instance(pk):
            return CardRevenue.objects.filter(pk=pk, tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = CardRevenue.objects.filter(pk=pk).first()
            return o is not None and o.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {"tenant": req.tenant, "created_by": su}

        return _n8n_upsert(
            request,
            serializer_class=N8nCardRevenueImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


class N8nPayrollLineUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant

        def get_instance(pk):
            return PayrollLine.objects.filter(pk=pk, document__tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = PayrollLine.objects.filter(pk=pk).select_related("document").first()
            return o is not None and o.document.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {}

        return _n8n_upsert(
            request,
            serializer_class=N8nPayrollLineImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


class N8nNoteUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant

        def get_instance(pk):
            return Note.objects.filter(pk=pk, tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = Note.objects.filter(pk=pk).first()
            return o is not None and o.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {"tenant": req.tenant, "created_by": su}

        return _n8n_upsert(
            request,
            serializer_class=N8nNoteImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )
