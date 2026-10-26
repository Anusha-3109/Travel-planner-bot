"""Per-session limits on live API calls.

The app gives each chat session its own SessionBudget and activates it while
the agent runs (`with use_budget(budget): ...`). Live requests call charge()
before going to the network; cached answers are free and never charged. When
no budget is active (scripts, tests), a fresh one with the default limits is
used for that process.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from backend import config


class LiveLimitError(RuntimeError):
    """The session has used all of its live calls for a service. Safe to show to users."""


@dataclass
class SessionBudget:
    limits: dict[str, int] = field(default_factory=lambda: dict(config.SESSION_LIMITS))
    used: dict[str, int] = field(default_factory=dict)

    def remaining(self, service: str) -> int | None:
        """Calls left this session, or None for a service without a limit (free services)."""
        if service not in self.limits:
            return None
        return max(self.limits[service] - self.used.get(service, 0), 0)

    def charge(self, service: str) -> None:
        if self.remaining(service) == 0:
            raise LiveLimitError(
                f"This chat has used all {self.limits.get(service, 0)} live {service} searches allowed per session. "
                "Using snapshot data instead. Start a new chat to search live again.")
        self.used[service] = self.used.get(service, 0) + 1


_default = SessionBudget()
_active: ContextVar[SessionBudget | None] = ContextVar("live_budget", default=None)


def current_budget() -> SessionBudget:
    return _active.get() or _default


@contextmanager
def use_budget(budget: SessionBudget):
    token = _active.set(budget)
    try:
        yield budget
    finally:
        _active.reset(token)
