"""Shared slowapi Limiter instance.

Lives in its own module — not `app/main.py` — specifically so route
modules can import `limiter` to decorate individual endpoints with
`@limiter.limit(...)` without a circular import (`app/main.py` imports
every route module to register its router; a route module importing
`limiter` back from `app/main.py` would be circular).

Registering `app.state.limiter` and the `RateLimitExceeded` exception
handler in `app/main.py` alone does NOT enforce anything — slowapi only
rate-limits a route that is actually decorated with `@limiter.limit(...)`
(or one covered by `SlowAPIMiddleware`, which this project doesn't use,
preferring explicit per-route limits so the policy is visible at each
endpoint). See `docs/architecture-decisions.md` for the audit finding
that led to this file existing.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings

settings = get_settings()
limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit_default])
