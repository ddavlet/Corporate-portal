# Each import causes the module's register() call to run, wiring the trigger
# into task_trigger_registry before the first request is handled.
import apps.modules.tasks.triggers.approval_step_activated  # noqa: F401
import apps.modules.tasks.triggers.approval_step_decided    # noqa: F401
import apps.modules.tasks.triggers.request_approved         # noqa: F401
import apps.modules.tasks.triggers.payment_confirmed        # noqa: F401
import apps.modules.tasks.triggers.request_rejected         # noqa: F401
import apps.modules.tasks.triggers.escalation               # noqa: F401
