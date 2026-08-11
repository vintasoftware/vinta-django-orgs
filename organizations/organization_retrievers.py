from __future__ import annotations

from typing import TYPE_CHECKING, cast

from django.contrib.sites.models import Site
from django.contrib.sites.shortcuts import get_current_site
from django.http import HttpRequest

from organizations.cache import (
    NO_ORGANIZATION,
    get_cached_organization_for_site,
    set_cached_organization_for_site,
)
from organizations.conf import get_organization_model
from organizations.exceptions import OrganizationNotFoundError
from organizations.models import OrganizationSite
from organizations.settings import get_setting

if TYPE_CHECKING:
    from organizations.models import Organization


def retrieve_by_domain(request: HttpRequest) -> Organization | None:
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
        return cast('Organization', cached)

    # ``original_manager`` because the scoped manager would need the very
    # organization this function exists to find. ``select_related`` fetches the
    # organization in the same query -- walking ``site.organization_site
    # .organization`` cost one query per hop, on every request.
    organization_site = OrganizationSite.original_manager.select_related('organization').filter(site=site).first()
    organization = organization_site.organization if organization_site is not None else None

    if site_id is not None:
        set_cached_organization_for_site(site_id, organization)

    return organization


def retrieve_by_http_header(request: HttpRequest) -> Organization | None:
    organization_model = get_organization_model()

    try:
        organization_http_header = 'HTTP_' + get_setting('ORGANIZATION_HTTP_HEADER').replace('-', '_').upper()
        return organization_model._default_manager.get(slug=request.META[organization_http_header])
    except LookupError:
        return None
    except organization_model.DoesNotExist as exc:
        raise OrganizationNotFoundError() from exc


def retrieve_by_session(request: HttpRequest) -> Organization | None:
    organization_model = get_organization_model()

    try:
        return organization_model._default_manager.get(slug=request.session['organization_slug'])
    except (AttributeError, LookupError, organization_model.DoesNotExist):
        return None
