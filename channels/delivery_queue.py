"""Thread-safe ordered outbox shared by communication channel plugins."""

from collections import deque
import threading
from typing import Callable, Iterable


class PartialDeliveryError(Exception):

    def __init__(self, remaining: str):
        super().__init__("Partial delivery; retaining unsent text")
        self.remaining = remaining


class PendingMessages:
    """Retain accepted messages until their delivery callback succeeds."""

    def __init__(self):
        self._items = deque()
        self._items_lock = threading.Lock()
        self._flush_lock = threading.Lock()

    def put(self, message: str) -> None:
        with self._items_lock:
            self._items.append(message)

    def extend(self, messages: Iterable[str]) -> None:
        with self._items_lock:
            self._items.extend(messages)

    def flush(
        self,
        deliver: Callable[[str], None],
        ready: Callable[[], bool] | None = None,
    ) -> None:
        """Deliver queued messages in order, retaining the head on failure."""
        if not self._flush_lock.acquire(blocking=False):
            return

        try:
            while ready is None or ready():
                with self._items_lock:
                    if not self._items:
                        return
                    message = self._items[0]

                try:
                    deliver(message)
                except PartialDeliveryError as exc:
                    with self._items_lock:
                        if self._items:
                            self._items[0] = exc.remaining
                    raise

                with self._items_lock:
                    if self._items:
                        self._items.popleft()
        finally:
            self._flush_lock.release()

    def clear(self) -> None:
        with self._items_lock:
            self._items.clear()

    def __len__(self) -> int:
        with self._items_lock:
            return len(self._items)
