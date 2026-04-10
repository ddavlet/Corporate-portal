import logging
from datetime import date, datetime

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modules.bank_expenses.models import BankExpense, BankRevenue
from apps.modules.clients_debt.models import ClientDebtSnapshot
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
    N8nClientDebtImportSerializer,
    N8nCashExpenseImportSerializer,
    N8nCashRevenueImportSerializer,
    N8nNoteImportSerializer,
    N8nPayrollLineImportSerializer,
    N8nRequestImportSerializer,
    N8nVendorImportSerializer,
)
from apps.tenants.integration_settings import get_n8n_integration_settings
from apps.tenants.permissions import IsTenantAdmin

User = get_user_model()
logger = logging.getLogger(__name__)


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


class _N8nBatchBaseView(_N8nBaseView):
    single_view_class = None

    @staticmethod
    def _item_request(base_request, item_data):
        class _Req:
            data = item_data
            tenant = base_request.tenant
            META = base_request.META
            method = base_request.method
            user = base_request.user
            path = base_request.path
            GET = getattr(base_request, "GET", {})

        return _Req()

    def post(self, request):
        if not isinstance(request.data, list):
            return Response({"detail": "Expected an array payload."}, status=status.HTTP_400_BAD_REQUEST)
        if self.single_view_class is None:
            return Response({"detail": "Batch view is not configured."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        single_view = self.single_view_class()
        results = []
        with transaction.atomic():
            for idx, item in enumerate(request.data):
                if not isinstance(item, dict):
                    transaction.set_rollback(True)
                    return Response(
                        {
                            "detail": "Batch failed. All changes rolled back.",
                            "failed_index": idx,
                            "failed_status": status.HTTP_400_BAD_REQUEST,
                            "failed_data": {"detail": "Each array item must be an object."},
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                item_request = self._item_request(request, item)
                try:
                    item_response = single_view.post(item_request)
                except Exception as exc:
                    logger.exception("n8n batch item processing failed: index=%s error=%s", idx, exc)
                    transaction.set_rollback(True)
                    return Response(
                        {
                            "detail": "Batch failed. All changes rolled back.",
                            "failed_index": idx,
                            "failed_status": status.HTTP_500_INTERNAL_SERVER_ERROR,
                            "failed_data": {"detail": "Unhandled server error."},
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                code = int(getattr(item_response, "status_code", status.HTTP_500_INTERNAL_SERVER_ERROR))
                if not 200 <= code < 300:
                    transaction.set_rollback(True)
                    return Response(
                        {
                            "detail": "Batch failed. All changes rolled back.",
                            "failed_index": idx,
                            "failed_status": code,
                            "failed_data": item_response.data,
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                results.append(
                    {
                        "index": idx,
                        "status": code,
                        "data": item_response.data,
                    }
                )

        return Response(
            {
                "count": len(results),
                "results": results,
            },
            status=status.HTTP_200_OK,
        )


def _proxy_n8n_json(request, endpoint: str):
    tenant = getattr(request, "tenant", None)
    if not tenant:
        return Response({"detail": "No tenant."}, status=status.HTTP_400_BAD_REQUEST)
    if not settings.BASE_DOMAIN:
        return Response({"detail": "BASE_DOMAIN is not configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    token = get_n8n_integration_settings(tenant=tenant).integration_token
    if not token:
        token = (getattr(settings, "N8N_INTEGRATION_TOKEN", None) or "").strip()
    if not token:
        return Response({"detail": "N8N_INTEGRATION_TOKEN is not configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    url = f"https://{tenant.subdomain}.{settings.BASE_DOMAIN}/{endpoint.lstrip('/')}"
    try:
        resp = requests.get(
            url,
            params=request.GET,
            timeout=20,
            headers={
                "Accept": "application/json",
                "X-N8N-Integration-Token": token,
                "X-Tenant": tenant.subdomain,
                "X-User-Id": str(request.user.id),
            },
        )
    except requests.RequestException as exc:
        logger.warning("n8n report proxy request failed: tenant=%s endpoint=%s error=%s", tenant.subdomain, endpoint, exc)
        return Response({"detail": f"n8n request failed: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)

    if resp.status_code in (401, 403):
        return Response({"detail": "Forbidden by n8n."}, status=status.HTTP_403_FORBIDDEN)
    if resp.status_code >= 400:
        return Response({"detail": f"n8n error {resp.status_code}"}, status=status.HTTP_502_BAD_GATEWAY)

    try:
        return Response(resp.json(), status=status.HTTP_200_OK)
    except ValueError:
        return Response({"detail": "Invalid JSON returned by n8n."}, status=status.HTTP_502_BAD_GATEWAY)


class N8nPnlDataView(_N8nBaseView):
    def get(self, request):
        return _proxy_n8n_json(request, "/pnl-data")


class N8nCashflowDataView(_N8nBaseView):
    def get(self, request):
        return _proxy_n8n_json(request, "/n8n/cashflow-data")


class PnlDataProxyView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return _proxy_n8n_json(request, "/n8n/pnl-data")


class CashflowDataProxyView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return _proxy_n8n_json(request, "/n8n/cashflow-data")


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
        su = _system_user()
        if su is None:
            return Response({"detail": "System user (pk=1) is missing."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        payload = dict(request.data)
        raw_id = payload.get("id")
        if raw_id not in (None, ""):
            try:
                int(raw_id)
            except (TypeError, ValueError):
                external_id = str(raw_id).strip()
                if not external_id:
                    return Response({"id": ["Must be an integer."]}, status=status.HTTP_400_BAD_REQUEST)
                payload.pop("id", None)
                payload.setdefault("external_id", external_id)

        if payload.get("id") in (None, "") and payload.get("external_id") not in (None, ""):
            create_ser = N8nCashExpenseImportSerializer(data=payload, context={"request": request})
            create_ser.is_valid(raise_exception=True)

            expense_year = create_ser.validated_data.get("expense_year")
            external_id = str(create_ser.validated_data.get("external_id") or "").strip()
            if external_id and expense_year is not None:
                existing = CashExpense.objects.filter(
                    tenant=tenant,
                    external_id=external_id,
                    expense_year=expense_year,
                ).first()
                if existing is not None:
                    update_ser = N8nCashExpenseImportSerializer(
                        instance=existing,
                        data=payload,
                        partial=True,
                        context={"request": request},
                    )
                    update_ser.is_valid(raise_exception=True)
                    try:
                        update_ser.save()
                    except IntegrityError:
                        return Response({"detail": "Could not update with this payload."}, status=status.HTTP_400_BAD_REQUEST)
                    return Response(update_ser.data, status=status.HTTP_200_OK)

            try:
                create_ser.save(tenant=request.tenant, created_by=su)
            except IntegrityError:
                return Response({"detail": "Could not create with this payload."}, status=status.HTTP_400_BAD_REQUEST)
            return Response(create_ser.data, status=status.HTTP_201_CREATED)

        def get_instance(pk):
            return CashExpense.objects.filter(pk=pk, tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = CashExpense.objects.filter(pk=pk).first()
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
        source_year = payload.get("source_year")
        if source_year in ("",):
            source_year = None
        if source_year is not None:
            try:
                source_year = int(source_year)
                payload["source_year"] = source_year
            except (TypeError, ValueError):
                source_year = None
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

        # Upsert by (external_id, source_year) when id is absent.
        if payload.get("id") in (None, "") and payload.get("external_id") not in (None, ""):
            ser_probe = N8nCashRevenueImportSerializer(data=payload, context={"request": request})
            ser_probe.is_valid(raise_exception=True)
            external_id = str(ser_probe.validated_data.get("external_id") or "").strip()
            effective_source_year = ser_probe.validated_data.get("source_year")
            existing_qs = CashRevenue.objects.filter(tenant=tenant, external_id=external_id)
            if effective_source_year is not None:
                existing_qs = existing_qs.filter(source_year=effective_source_year)
            existing = existing_qs.first()
            if existing is not None:
                update_ser = N8nCashRevenueImportSerializer(
                    instance=existing,
                    data=payload,
                    partial=True,
                    context={"request": request},
                )
                update_ser.is_valid(raise_exception=True)
                try:
                    update_ser.save()
                except IntegrityError:
                    return Response({"detail": "Could not update with this payload."}, status=status.HTTP_400_BAD_REQUEST)
                return Response(update_ser.data, status=status.HTTP_200_OK)
            try:
                ser_probe.save(tenant=request.tenant, created_by=su)
            except IntegrityError:
                return Response({"detail": "Could not create with this payload."}, status=status.HTTP_400_BAD_REQUEST)
            return Response(ser_probe.data, status=status.HTTP_201_CREATED)

        if raw_id not in (None, ""):
            try:
                int(raw_id)
            except (TypeError, ValueError):
                external_id = str(raw_id).strip()
                if not external_id:
                    return Response({"id": ["Must be an integer."]}, status=status.HTTP_400_BAD_REQUEST)
                payload.pop("id", None)
                payload.setdefault("external_id", external_id)

                existing_qs = CashRevenue.objects.filter(tenant=tenant, external_id=external_id)
                if source_year is not None:
                    existing_qs = existing_qs.filter(source_year=source_year)
                existing = existing_qs.first()
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


class N8nClientsDebtUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant
        raw_snapshot_at = request.data.get("snapshot_at", request.data.get("date"))
        client_name = str(request.data.get("client") or "").strip()
        snapshot_date = None
        if isinstance(raw_snapshot_at, datetime):
            snapshot_date = raw_snapshot_at.date()
        elif isinstance(raw_snapshot_at, date):
            snapshot_date = raw_snapshot_at
        elif raw_snapshot_at not in (None, ""):
            raw = str(raw_snapshot_at).strip()
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            try:
                snapshot_date = datetime.fromisoformat(raw).date()
            except ValueError:
                try:
                    snapshot_date = date.fromisoformat(raw)
                except ValueError:
                    snapshot_date = None

        # Support upsert by natural key (snapshot_at date, client) when id is omitted.
        if request.data.get("id") in (None, "") and snapshot_date is not None and client_name:
            existing = ClientDebtSnapshot.objects.filter(
                tenant=tenant,
                snapshot_at__date=snapshot_date,
                client=client_name,
            ).first()
            if existing is not None:
                ser = N8nClientDebtImportSerializer(
                    instance=existing,
                    data=request.data,
                    partial=True,
                    context={"request": request},
                )
                ser.is_valid(raise_exception=True)
                try:
                    ser.save()
                except IntegrityError:
                    return Response({"detail": "Could not update with this payload."}, status=status.HTTP_400_BAD_REQUEST)
                return Response(ser.data, status=status.HTTP_200_OK)

        def get_instance(pk):
            return ClientDebtSnapshot.objects.filter(pk=pk, tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = ClientDebtSnapshot.objects.filter(pk=pk).first()
            return o is not None and o.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {"tenant": req.tenant, "created_by": su}

        return _n8n_upsert(
            request,
            serializer_class=N8nClientDebtImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


class N8nPayrollLineUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant
        raw_doc_id = request.data.get("doc_id")
        raw_line_no = request.data.get("line_no")
        doc_id = str(raw_doc_id or "").strip()
        line_no = None
        if raw_line_no not in (None, ""):
            try:
                line_no = int(raw_line_no)
            except (TypeError, ValueError):
                line_no = None

        # Support upsert by natural key (doc_id, line_no) when id is omitted.
        if request.data.get("id") in (None, "") and doc_id and line_no is not None:
            existing = PayrollLine.objects.filter(
                document__tenant=tenant,
                document__doc_id=doc_id,
                line_no=line_no,
            ).first()
            if existing is not None:
                ser = N8nPayrollLineImportSerializer(
                    instance=existing,
                    data=request.data,
                    partial=True,
                    context={"request": request},
                )
                ser.is_valid(raise_exception=True)
                try:
                    ser.save()
                except IntegrityError:
                    return Response({"detail": "Could not update with this payload."}, status=status.HTTP_400_BAD_REQUEST)
                return Response(ser.data, status=status.HTTP_200_OK)

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


class N8nVendorBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nVendorUpsertView


class N8nRequestBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nRequestUpsertView


class N8nApprovalBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nApprovalUpsertView


class N8nCashExpenseBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nCashExpenseUpsertView


class N8nCashRevenueBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nCashRevenueUpsertView


class N8nBankExpenseBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nBankExpenseUpsertView


class N8nBankRevenueBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nBankRevenueUpsertView


class N8nCardExpenseBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nCardExpenseUpsertView


class N8nCardRevenueBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nCardRevenueUpsertView


class N8nClientsDebtBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nClientsDebtUpsertView


class N8nPayrollLineBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nPayrollLineUpsertView


class N8nNoteBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nNoteUpsertView
