"""Startup checks for configurations that make a security control a no-op.

Registered from ``OrganizationsConfig.ready()``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.core.checks import Warning as CheckWarning

from vinta_orgs.settings import get_setting

if TYPE_CHECKING:
    from django.apps import AppConfig
    from django.core.checks import CheckMessage

AUTHENTICATION_MIDDLEWARE = 'django.contrib.auth.middleware.AuthenticationMiddleware'
ORGANIZATION_MIDDLEWARE = 'vinta_orgs.middleware.OrganizationMiddleware'

#: The retrievers that read something the *caller* chose, and so are the ones
#: ``VERIFY_ORGANIZATION_MEMBERSHIP`` guards. ``retrieve_by_domain`` is absent on
#: purpose: the host is not the caller's to pick.
CALLER_SUPPLIED_RETRIEVERS = frozenset(
    {
        'vinta_orgs.organization_retrievers.retrieve_by_http_header',
        'vinta_orgs.organization_retrievers.retrieve_by_session',
        'vinta_orgs.organization_retrievers.retrieve_by_user_membership',
    }
)


def check_middleware_order(
    *,
    app_configs: Sequence[AppConfig] | None = None,
    databases: Sequence[str] | None = None,
    **kwargs: Any,
) -> list[CheckMessage]:
    """``OrganizationMiddleware`` must come after ``AuthenticationMiddleware``.

    The membership check in ``_verify_membership`` reads ``request.user``, and
    a request whose ``AuthenticationMiddleware`` has not run yet has no ``user``
    attribute at all. The check then cannot run, and a header naming another
    tenant selects it -- silently, and only on the requests that resolve early
    enough to matter, which is why this is worth reporting at startup rather
    than leaving to be discovered.

    A warning rather than an error: the ordering is only *unsafe*, not broken,
    and a project that resolves by domain alone is unaffected either way.
    """
    middleware = list(getattr(settings, 'MIDDLEWARE', None) or [])

    if ORGANIZATION_MIDDLEWARE not in middleware or AUTHENTICATION_MIDDLEWARE not in middleware:
        return []

    if not get_setting('VERIFY_ORGANIZATION_MEMBERSHIP'):
        return []

    if not CALLER_SUPPLIED_RETRIEVERS.intersection(get_setting('ORGANIZATION_RETRIEVERS') or []):
        return []

    if middleware.index(ORGANIZATION_MIDDLEWARE) > middleware.index(AUTHENTICATION_MIDDLEWARE):
        return []

    return [
        CheckWarning(
            'OrganizationMiddleware runs before AuthenticationMiddleware, so the organization '
            'a request names cannot be checked against the caller.',
            hint=(
                'Move %r after %r in MIDDLEWARE. Until you do, VERIFY_ORGANIZATION_MEMBERSHIP has '
                'no effect on any request that resolves its organization before request.user exists, '
                'and an authenticated caller can select another organization by naming its slug.'
                % (ORGANIZATION_MIDDLEWARE, AUTHENTICATION_MIDDLEWARE)
            ),
            id='vinta_orgs.W001',
        )
    ]
