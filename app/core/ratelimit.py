"""Small in-process rate limiter for sensitive endpoints (login, assistant).

Suitable for a single-process deployment. Behind multiple workers use a shared
store instead; this is documented in the deployment guide.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

_HITS: dict[str, deque] = defaultdict(deque)


def allow(key: str, limit: int, window_seconds: int) -> bool:
    now = time.time()
    bucket = _HITS[key]
    while bucket and bucket[0] < now - window_seconds:
        bucket.popleft()
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True


def reset(key: str | None = None) -> None:
    if key is None:
        _HITS.clear()
    else:
        _HITS.pop(key, None)
