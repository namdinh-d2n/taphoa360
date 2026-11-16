"""Wake SSE subscribers after committed writes; callbacks never run in a transaction."""

import asyncio
from contextlib import contextmanager
from pathlib import Path
import threading

_lock = threading.Lock()
_subscribers = {}


def database_key(database):
    return str(Path(database).resolve())


@contextmanager
def subscribe(database):
    loop = asyncio.get_running_loop()
    event = asyncio.Event()
    key = database_key(database)
    entry = (loop, event)
    with _lock:
        _subscribers.setdefault(key, set()).add(entry)
    try:
        yield event
    finally:
        with _lock:
            listeners = _subscribers.get(key, set())
            listeners.discard(entry)
            if not listeners:
                _subscribers.pop(key, None)


def publish(database):
    with _lock:
        listeners = tuple(_subscribers.get(database_key(database), ()))
    for loop, event in listeners:
        try:
            loop.call_soon_threadsafe(event.set)
        except RuntimeError:
            # An event loop may close while a request is being cancelled.
            pass
