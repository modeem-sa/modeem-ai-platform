"""In-memory rate limiting for login attempts.

Blocks repeated failed login attempts per (client IP, email) key.
Successful logins reset the counter, so legitimate users are unaffected.

Note: state is per-process. For multi-instance deployments this should be
backed by Redis (settings.redis_url is already reserved for that).
"""

import threading
import time
from dataclasses import dataclass, field


@dataclass
class _Entry:
    failures: int = 0
    window_start: float = 0.0
    blocked_until: float = 0.0
    last_seen: float = field(default_factory=time.monotonic)


class LoginRateLimiter:
    """Fixed-window limiter: after `max_attempts` failures within
    `window_seconds`, the key is blocked for `block_seconds`."""

    def __init__(
        self,
        max_attempts: int = 5,
        window_seconds: float = 60.0,
        block_seconds: float = 300.0,
    ) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.block_seconds = block_seconds
        self._entries: dict[tuple[str, str], _Entry] = {}
        self._lock = threading.Lock()

    def _now(self) -> float:  # separated for testability
        return time.monotonic()

    def retry_after(self, ip: str, email: str) -> int | None:
        """Seconds until the key is allowed again, or None if not blocked."""
        now = self._now()
        with self._lock:
            self._prune(now)
            entry = self._entries.get((ip, email))
            if entry is None or entry.blocked_until <= now:
                return None
            return max(1, int(entry.blocked_until - now + 0.999))

    def record_failure(self, ip: str, email: str) -> None:
        now = self._now()
        with self._lock:
            self._prune(now)
            entry = self._entries.setdefault((ip, email), _Entry(window_start=now))
            entry.last_seen = now
            if now - entry.window_start > self.window_seconds:
                entry.failures = 0
                entry.window_start = now
            entry.failures += 1
            if entry.failures >= self.max_attempts:
                entry.blocked_until = now + self.block_seconds

    def record_success(self, ip: str, email: str) -> None:
        with self._lock:
            self._entries.pop((ip, email), None)

    def reset(self) -> None:
        with self._lock:
            self._entries.clear()

    def _prune(self, now: float) -> None:
        # Drop stale entries so memory stays bounded.
        ttl = max(self.window_seconds, self.block_seconds) * 2
        stale = [k for k, e in self._entries.items() if now - e.last_seen > ttl]
        for k in stale:
            del self._entries[k]


login_rate_limiter = LoginRateLimiter()
