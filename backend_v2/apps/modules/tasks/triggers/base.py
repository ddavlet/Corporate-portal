from __future__ import annotations

import abc


class AbstractTaskTrigger(abc.ABC):
    """Base contract for all auto-task triggers.

    OCP rule: adding a new event = new subclass + register() call in autodiscover.py.
    Never add elif branches to the registry or existing triggers.
    """

    # Each subclass must declare the event name it handles.
    event_name: str

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not hasattr(cls, "event_name") or not cls.event_name:
            raise TypeError(f"{cls.__name__} must define a non-empty 'event_name' class attribute.")

    @abc.abstractmethod
    def handle(self, **context) -> None:
        """Execute the trigger logic. context kwargs are event-specific."""
        raise NotImplementedError
