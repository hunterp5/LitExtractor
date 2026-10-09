"""In-process OpenChemIE client reuse and serialization."""

from __future__ import annotations

from contextlib import contextmanager
from threading import RLock
from typing import Any, Callable, Iterator

_client_lock = RLock()
_cached_client: tuple[str, Any] | None = None


@contextmanager
def openchemie_client_session() -> Iterator[None]:
    """Serialize extraction jobs that share the cached, stateful OpenChemIE client."""
    with _client_lock:
        yield


def get_cached_openchemie_client(device: str, factory: Callable[[], Any]) -> Any:
    """Get the process-wide OpenChemIE client for *device*, creating it once as needed."""
    global _cached_client
    with _client_lock:
        if _cached_client is None or _cached_client[0] != device:
            _cached_client = (device, factory())
        return _cached_client[1]