"""Brakes against guessing: a count per key in the cache, with a window. A wrong password on a sharing link and requests to a
public page count against the visitor's address, and when the count is over the limit the next try is refused until the window
has passed, even with the right password."""
from django.core.cache import cache

from apps.audit.log import client_ip


def _key(kind, *parts):
    return 'throttle:' + kind + ':' + ':'.join(str(p).lower() for p in parts)


def count(key) -> int:
    return cache.get(key, 0)


def hit(key, window) -> int:
    cache.add(key, 0, window)
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, window)
        return 1


def clear(key):
    cache.delete(key)


def over(request, kind, limit_window) -> bool:
    """Count one try of `kind` from this address; True when it is over the limit."""
    limit, window = limit_window
    return hit(_key(kind, client_ip(request) or 'none'), window) > limit
