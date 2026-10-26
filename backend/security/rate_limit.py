"""Simple sliding-window rate limiter, kept per Streamlit session."""

import time
from collections import deque


class RateLimiter:
    def __init__(self, max_requests: int = 15, window_seconds: int = 300) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._timestamps: deque[float] = deque()

    def _prune(self, now: float) -> None:
        while self._timestamps and now - self._timestamps[0] > self.window_seconds:
            self._timestamps.popleft()

    def try_acquire(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        self._prune(now)
        if len(self._timestamps) >= self.max_requests:
            return False
        self._timestamps.append(now)
        return True

    def seconds_until_available(self, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        self._prune(now)
        if len(self._timestamps) < self.max_requests:
            return 0
        return int(self.window_seconds - (now - self._timestamps[0])) + 1
