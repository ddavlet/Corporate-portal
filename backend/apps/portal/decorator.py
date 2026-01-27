from django.http import HttpResponseForbidden
from functools import wraps

def require_finance_report_access(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        m = getattr(request, "membership", None)
        if not m or not m.is_active:
            return HttpResponseForbidden("No membership on request")
        if not m.can_view_finance_report:
            return HttpResponseForbidden("No access")
        return view_func(request, *args, **kwargs)
    return wrapped
