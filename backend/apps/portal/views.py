import requests
from django.shortcuts import render, redirect
from django.http import JsonResponse, StreamingHttpResponse, HttpResponseForbidden, HttpResponseServerError
from django.conf import settings
from django.contrib.auth.decorators import login_required

from apps.portal.decorator import require_finance_report_access



def tenant_home(request):

    tenant = getattr(request, "tenant", None)

    return render(
        request,
        "portal/tenant_home.html",
        {
            "tenant": tenant,
            "login_host": getattr(settings, "LOGIN_HOST", "login.kolberg.uz"),
        },
    )


def requests_page(request):
    # пока просто страница-заглушка (позже вставим твой шаблон requests.html)
    return render(request, "portal/requests.html")


def vendors_page(request):
    # страница-заглушка (позже сделаем список поставщиков)
    return render(request, "portal/vendors.html")


def _proxy_n8n_json(request, endpoint: str):

    tenant = getattr(request, "tenant", None)
    if not tenant:
        return HttpResponseForbidden("No tenant")

    url = f"https://{tenant.subdomain}.{settings.BASE_DOMAIN}/{endpoint.lstrip('/')}"

    try:
        resp = requests.get(
            url,
            params=request.GET,
            timeout=20,
            headers={
                "Accept": "application/json",
                "X-N8N-Token": settings.N8N_TOKEN,
                "X-Tenant": tenant.subdomain,
                "X-User-Id": str(request.user.id),
            },
        )

        if resp.status_code in (401, 403):
            return HttpResponseForbidden("Forbidden by n8n")
        if resp.status_code >= 400:
            return HttpResponseServerError(f"n8n error {resp.status_code}")

        return JsonResponse(resp.json(), safe=False)
    except requests.RequestException as e:
        return HttpResponseServerError(f"n8n request failed: {e}")


def requests_data(request):
    return _proxy_n8n_json(request, "/requests-data")


def vendors_data(request):
    return _proxy_n8n_json(request, "/vendors-data")


def vendor_request_data(request):
    return _proxy_n8n_json(request, "/vendor-request-data")


@require_finance_report_access
def pnl_data(request):
    data = {
        "year": 2018,
        "currency": "USD",
        "unit": "millions",
        "months": ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"],
        "rows": [
            {
                "key": "revenue_1",
                "label": "Revenue stream 1",
                "values": [587.0, 596.3, 605.8, 615.4, 625.2, 635.1, 645.2, 655.4, 665.8, 676.4, 687.1, 698.0],
                "total": 7692.6
            },
            {
                "key": "returns",
                "label": "Returns, Refunds, Discounts",
                "values": [-21.0, -21.3, -21.7, -22.0, -22.4, -22.7, -23.1, -23.5, -23.8, -24.2, -24.6, -25.0],
                "total": -275.3,
                "style": "negative"
            },
            {
                "key": "total_net_revenue",
                "label": "Total Net Revenue",
                "values": [711.6, 722.9, 734.3, 746.0, 757.8, 769.9, 782.1, 794.5, 807.1, 819.9, 832.9, 846.1],
                "total": 9325.0,
                "bold": True
            },
            {
                "key": "expenses",
                "label": "Expenses",
                "section": True
            },
            {
                "key": "advertising",
                "label": "Advertising & Promotion",
                "values": [18.7, 19.1, 19.5, 19.8, 20.2, 20.6, 21.0, 21.5, 21.9, 22.3, 22.8, 23.2],
                "total": 250.6,
                "indent": 1
            }
        ]
    }
    return JsonResponse(data)


@require_finance_report_access
def reports_page(request):
    return render(request, 'portal/reports/reports.html')


@require_finance_report_access
def pnl_page(request):
    return render(request, "portal/reports/pnl.html")

def _proxy_n8n_file(request):
    """
    GET /web/file?filename=<name>
    Proxies to /getfile on the tenant host with X-N8N-Token
    and streams the response back to the client.
    """
    tenant = getattr(request, "tenant", None)
    if not tenant:
        return HttpResponseForbidden("No tenant")
    filename = request.GET.get("filename", "")
    url = f"https://{tenant.subdomain}.{settings.BASE_DOMAIN}/getfile"

    try:
        resp = requests.get(
            url,
            params={"filename": filename},
            timeout=60,
            stream=True,
            headers={
                "Accept": "*/*",
                "X-N8N-Token": settings.N8N_TOKEN,
                "X-Tenant": tenant.subdomain,
                "X-User-Id": str(request.user.id),
            },
        )

        if resp.status_code in (401, 403):
            return HttpResponseForbidden("Forbidden by n8n")
        if resp.status_code >= 400:
            return HttpResponseServerError(f"n8n error {resp.status_code}")

        # Stream back to user
        proxy = StreamingHttpResponse(
            streaming_content=resp.iter_content(chunk_size=1024 * 64),
            status=resp.status_code,
            content_type=resp.headers.get("Content-Type", "application/octet-stream"),
        )

        # Forward useful headers
        content_length = resp.headers.get("Content-Length")
        if content_length:
            proxy["Content-Length"] = content_length

        content_disp = resp.headers.get("Content-Disposition")
        if content_disp:
            proxy["Content-Disposition"] = content_disp
        else:
            # default download name
            proxy["Content-Disposition"] = f'attachment; filename="{filename}"'

        return proxy

    except requests.RequestException as e:
        return HttpResponseServerError(f"n8n request failed: {e}")

def get_file(request):
    return _proxy_n8n_file(request)
