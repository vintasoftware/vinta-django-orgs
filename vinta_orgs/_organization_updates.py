"""Internal propagation for explicitly authorized organization relocation."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar

_organization_update_is_allowed: ContextVar[bool] = ContextVar(
    'vinta_orgs.organization_update_is_allowed', default=False
)


def organization_update_is_allowed() -> bool:
    return _organization_update_is_allowed.get()


@contextlib.contextmanager
def allow_organization_update() -> Iterator[None]:
    """Propagate one public unsafe opt-out through nested Django ORM calls."""
    token = _organization_update_is_allowed.set(True)
    try:
        yield
    finally:
        _organization_update_is_allowed.reset(token)
