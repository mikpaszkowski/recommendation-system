from typing import Dict, List, Optional

from src.conversation.abstract_history_manager import AbstractHistoryManager


class InMemoryHistoryManager(AbstractHistoryManager):
    """
    Simple in-memory history store.

    Keeps recent conversation turns per user. This is intentionally minimal
    to stay easy to swap for a persistent implementation later.
    """

    def __init__(self, max_turns: int = 20) -> None:
        self._store: Dict[str, List[Dict[str, str]]] = {}
        self._max_turns = max_turns

    def get_history(self, user_id: str) -> List[Dict[str, str]]:
        """Return conversation history for a user (most recent first)."""
        return self._store.get(user_id, [])

    def add_turn(
        self,
        user_id: str,
        user_message: str,
        assistant_message: Optional[str] = None,
    ) -> None:
        """Append a turn and trim history to the configured window."""
        history = self._store.setdefault(user_id, [])
        turn: Dict[str, str] = {"user": user_message}
        if assistant_message is not None:
            turn["assistant"] = assistant_message
        history.insert(0, turn)
        if len(history) > self._max_turns:
            self._store[user_id] = history[: self._max_turns]

