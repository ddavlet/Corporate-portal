from django.http import HttpResponseForbidden

def require_finance_report_access(view_func):
    def wrapped(request, *args, **kwargs):
        m = getattr(request, "membership", None)
        if not m or not m.can_view_finance_report:
            return HttpResponseForbidden("Forbidden")
        return view_func(request, *args, **kwargs)
    return wrapped
