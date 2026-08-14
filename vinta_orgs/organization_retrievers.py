from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.sites.models import Site
from django.contrib.sites.shortcuts import get_current_site
from django.http import HttpRequest

from vinta_orgs.cache import (
    NO_ORGANIZATION,
    get_cached_organization_for_site,
    set_cached_organization_for_site,
)
from vinta_orgs.conf import get_organization_membership_model, get_organization_model
from vinta_orgs.exceptions import OrganizationAccessDeniedError, OrganizationNotFoundError
from vinta_orgs.helpers.memberships import resolve_organization_for_user
from vinta_orgs.models import OrganizationSite
from vinta_orgs.settings import get_setting

if TYPE_CHECKING:
    from vinta_orgs.models import AbstractOrganization


def retrieve_by_domain(request: HttpRequest) -> AbstractOrganization | None:
    try:
        site = get_current_site(request)
    except Site.DoesNotExist:
        return None

    # ``get_current_site`` falls back to a ``RequestSite`` when
    # ``django.contrib.sites`` is not installed, and that one is built from the
    # request rather than from a row -- there is nothing stable to key a cache
    # on, so caching is skipped rather than guessed at.
    site_id = getattr(site, 'pk', None)

    # Only consulted when ``CACHE_ORGANIZATION_RETRIEVAL`` is on; otherwise this
    # is a miss every time and the query below runs as it always has.
    cached = get_cached_organization_for_site(site_id) if site_id is not None else None

    if cached == NO_ORGANIZATION:
        return None

    if cached is not None:
        return cached

    # ``original_manager`` because the scoped manager would need the very
    # organization this function exists to find. ``select_related`` fetches the
    # organization in the same query -- walking ``site.organization_site
    # .organization`` cost one query per hop, on every request.
    organization_site = OrganizationSite.original_manager.select_related('organization').filter(site=site).first()
    organization = organization_site.organization if organization_site is not None else None

    if site_id is not None:
        set_cached_organization_for_site(site_id, organization)

    return organization


def _verify_membership(request: HttpRequest, organization: AbstractOrganization) -> None:
    """Refuse a caller-named organization the authenticated caller does not belong to.

    ``retrieve_by_domain`` needs nothing of the sort: the host is the authority
    there, and it is not the caller's to choose. A header and a session key are
    a different matter -- the header is set by whoever is making the request, and
    the session key is only ever as trustworthy as whatever wrote it. Without
    this check any authenticated user selects any tenant by sending its slug,
    and every scoped manager in the process then serves that tenant's rows.

    Two cases are deliberately let through:

    * **An anonymous request.** There is no membership to check and no privilege
      to escalate; the caller gets whatever that organization exposes publicly,
      exactly as they would by visiting its domain.
    * **A request with no ``user`` attribute at all**, which is what
      ``AuthenticationMiddleware`` not having run yet looks like. Guessing would
      mean either refusing every request on such a project or authenticating a
      second time here. The system check ``vinta_orgs.W001`` reports the
      middleware ordering that causes it, so this is a warned-about
      configuration rather than a silent hole.

    Set ``VERIFY_ORGANIZATION_MEMBERSHIP`` to ``False`` to skip the check --
    appropriate when the header is a routing hint in front of a surface that
    authorizes every read on its own, and nothing else.
    """
    if not get_setting('VERIFY_ORGANIZATION_MEMBERSHIP'):
        return

    user = getattr(request, 'user', None)

    if user is None or not user.is_authenticated:
        return

    # Not ``get_active_memberships``: this only needs to know whether a row
    # exists, and that helper sorts and joins the organization for callers that
    # go on to read it.
    memberships = get_organization_membership_model()._default_manager

    if not memberships.filter(user_id=user.pk, organization_id=organization.pk, is_active=True).exists():
        raise OrganizationAccessDeniedError()


def retrieve_by_http_header(request: HttpRequest) -> AbstractOrganization | None:
    """The organization named by the ``ORGANIZATION_HTTP_HEADER`` header.

    An authenticated caller must hold an active membership in it; see
    :func:`_verify_membership`.
    """
    organization_model = get_organization_model()

    try:
        organization_http_header = 'HTTP_' + get_setting('ORGANIZATION_HTTP_HEADER').replace('-', '_').upper()
        organization = organization_model._default_manager.get(slug=request.META[organization_http_header])
    except LookupError:
        return None
    except organization_model.DoesNotExist as exc:
        raise OrganizationNotFoundError() from exc

    _verify_membership(request, organization)

    return organization


def retrieve_by_session(request: HttpRequest) -> AbstractOrganization | None:
    """The organization whose slug the session holds.

    Membership-checked like the header is. The value is written by
    ``ADD_ORGANIZATION_TO_SESSION`` from an already-resolved organization, so on
    the ordinary path this re-checks something that was checked once -- but the
    key is a plain session entry that any view may write, and a session outlives
    the request that filled it.
    """
    organization_model = get_organization_model()

    try:
        organization = organization_model._default_manager.get(slug=request.session['organization_slug'])
    except (AttributeError, LookupError, organization_model.DoesNotExist):
        return None

    _verify_membership(request, organization)

    return organization


def retrieve_by_user_membership(request: HttpRequest) -> AbstractOrganization | None:
    """The authenticated caller's own organization, when they have exactly one.

    Not in ``ORGANIZATION_RETRIEVERS`` by default -- it only makes sense on a
    project where a user's memberships are what selects the organization, rather
    than the domain or an explicit header. Add it *last*, after the retrievers
    that read something the caller said::

        SHARED_SCHEMA_ORGANIZATIONS = {
            'ORGANIZATION_RETRIEVERS': [
                'vinta_orgs.organization_retrievers.retrieve_by_domain',
                'vinta_orgs.organization_retrievers.retrieve_by_http_header',
                'vinta_orgs.organization_retrievers.retrieve_by_user_membership',
            ],
        }

    A caller with several memberships and nothing naming one raises
    ``AmbiguousOrganizationError`` (a ``BadRequest``, so a 400) rather than
    resolving to whichever membership is oldest. See
    :func:`vinta_orgs.helpers.memberships.resolve_membership_for_user` for the
    full table.
    """
    return resolve_organization_for_user(getattr(request, 'user', None))
