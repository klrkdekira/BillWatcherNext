"""A small in-process rate limiter (HANDOFF 13, 17).

Ordinary browsing is never limited. Search is limited loosely and answers strictly, so an
expensive feature cannot be used to exhaust the service.
"""

import time
from collections import OrderedDict
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RateLimit:
    capacity: int
    refill_per_second: float


class RateLimiter:
    def __init__(self, limit: RateLimit, *, max_keys: int = 4096) -> None:
        self.limit = limit
        self.max_keys = max_keys
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def allow(self, key: str, *, now: float | None = None) -> bool:
        moment = time.monotonic() if now is None else now
        tokens, last = self._buckets.get(key, (float(self.limit.capacity), moment))
        tokens = min(
            float(self.limit.capacity),
            tokens + (moment - last) * self.limit.refill_per_second,
        )
        if tokens < 1.0:
            self._buckets[key] = (tokens, moment)
            self._buckets.move_to_end(key)
            return False
        self._buckets[key] = (tokens - 1.0, moment)
        self._buckets.move_to_end(key)
        while len(self._buckets) > self.max_keys:
            self._buckets.popitem(last=False)
        return True
