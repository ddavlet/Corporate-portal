import logging

from django.db import transaction

logger = logging.getLogger(__name__)


def _run_turn_later(node_id: int) -> None:
    # Placeholder: the real agent turn is implemented in a later task.
    logger.info("ai_assistant: agent turn for node=%s not implemented yet", node_id)


def submit_turn(node_id: int) -> None:
    """Schedule the agent turn once the surrounding transaction has committed."""
    transaction.on_commit(lambda: _run_turn_later(node_id))
