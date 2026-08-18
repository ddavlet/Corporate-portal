from django.conf import settings
from django.core.checks import Warning, register


@register()
def check_messaging_gateway_url(app_configs, **kwargs):
    errors = []
    if getattr(settings, "DEBUG", False):
        return errors
    url = (getattr(settings, "MESSAGING_GATEWAY_SEND_URL", "") or "").strip()
    if not url:
        errors.append(Warning(
            "MESSAGING_GATEWAY_SEND_URL is not configured. "
            "All Telegram approval/notification messages will fail silently.",
            hint="Set MESSAGING_GATEWAY_SEND_URL in the environment "
                 "(e.g. http://tg_gateway:8080/send).",
            id="telegram_approvals.W001",
        ))
    return errors
