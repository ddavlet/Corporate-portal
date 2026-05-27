from __future__ import annotations

import logging
import traceback

from apps.modules.tasks.triggers.base import AbstractTaskTrigger

logger = logging.getLogger(__name__)


class TaskTriggerRegistry:
    """Dispatches events to registered trigger handlers.

    OCP: extend by calling register() with a new trigger instance.
    Never add if/elif blocks here to handle specific events.

    Error isolation: a failing trigger is logged with full traceback
    but never prevents other registered triggers from running.
    """

    def __init__(self) -> None:
        self._triggers: dict[str, list[AbstractTaskTrigger]] = {}

    def register(self, trigger: AbstractTaskTrigger) -> None:
        event = trigger.event_name
        self._triggers.setdefault(event, []).append(trigger)
        logger.debug("TaskTriggerRegistry: registered %s for event '%s'", type(trigger).__name__, event)

    def dispatch(self, event_name: str, **context) -> None:
        handlers = self._triggers.get(event_name, [])
        if not handlers:
            logger.debug("TaskTriggerRegistry: no handlers for event '%s'", event_name)
            return

        for trigger in handlers:
            try:
                trigger.handle(**context)
            except Exception:
                logger.error(
                    "TaskTriggerRegistry: error in %s while handling event '%s' "
                    "(context keys: %s):\n%s",
                    type(trigger).__name__,
                    event_name,
                    list(context.keys()),
                    traceback.format_exc(),
                )


# Module-level singleton — imported by autodiscover.py and all trigger modules.
task_trigger_registry = TaskTriggerRegistry()
