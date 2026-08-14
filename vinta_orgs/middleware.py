from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from django.http import HttpRequest
from django.http.response import HttpResponseBase
from django.utils.functional import SimpleLazyObject

from vinta_orgs.settings import get_setting
from vinta_orgs.state import (
    OrganizationToken,
    clear_current_organization,
    get_current_organization,
    reset_current_organization,
    set_current_organization,
)
from vinta_orgs.utils import import_from_string

if TYPE_CHECKING:
    from vinta_orgs.models import AbstractOrganization


class OrganizationRequest(HttpRequest):
    """The request as :class:`OrganizationMiddleware` leaves it.

    Nothing is ever instantiated from this class -- Django builds the request,
    and the middleware attaches the attributes below to whatever it is handed.
    It exists so that ``request.organization`` has a name and a type, both for
    the middleware itself and for the views and helpers a project writes
    against it::

        def my_view(request: OrganizationRequest) -> HttpResponse:
            ...
    """

    #: The organization this request belongs to, resolved on first read.
    organization: AbstractOrganization | None
    #: Memoizes :func:`get_organization` for the life of the request.
    _cached_organization: AbstractOrganization | None
    #: Whatever was bound before the request started, used as a fallback.
    _organization_before_request: AbstractOrganization | None
    #: Restores that previous binding once the response is on its way out.
    _organization_token: OrganizationToken


_UNSET: Any = object()


def get_organization(request: HttpRequest) -> AbstractOrganization | None:
    """Resolve the organization this request belongs to, at most once per request."""
    stashed = cast('OrganizationRequest', request)

    if not hasattr(request, '_cached_organization'):
        stashed._cached_organization = _retrieve_organization(request)

    return stashed._cached_organization


def _retrieve_organization(request: HttpRequest) -> AbstractOrganization | None:
    for organization_retriever in get_setting('ORGANIZATION_RETRIEVERS'):
        organization = import_from_string(organization_retriever)(request)

        if organization:
            if get_setting('ADD_ORGANIZATION_TO_SESSION'):
                try:
                    # Only on a change. Assigning marks the session modified,
                    # and ``SessionMiddleware`` then saves it -- which on the
                    # database backend is a write on *every* request, to store
                    # the slug that was already there.
                    if request.session.get('organization_slug') != organization.slug:
                        request.session['organization_slug'] = organization.slug
                except AttributeError:
                    pass

            return cast('AbstractOrganization', organization)

    # No retriever recognized the request. Fall back to whatever was bound to
    # this context *before* the request started -- an organization set by a
    # test, a task or a management command. Reading the binding the middleware
    # itself just installed would recurse, which is why the previous value is
    # stashed on the request instead of read back from the context.
    fallback = getattr(request, '_organization_before_request', _UNSET)
    if fallback is _UNSET:
        fallback = get_current_organization()

    return cast('AbstractOrganization | None', fallback)


class OrganizationMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponseBase]) -> None:
        self.get_response = get_response

    @classmethod
    def get_current_organization(cls) -> AbstractOrganization | None:
        return get_current_organization()

    @classmethod
    def set_organization(cls, organization: AbstractOrganization | str | None) -> OrganizationToken:
        return set_current_organization(organization)

    @classmethod
    def clear_organization(cls) -> OrganizationToken:
        return clear_current_organization()

    def process_request(self, request: HttpRequest) -> OrganizationRequest:
        stashed = cast('OrganizationRequest', request)

        stashed._organization_before_request = get_current_organization()
        stashed.organization = cast('AbstractOrganization', SimpleLazyObject(lambda: get_organization(request)))
        stashed._organization_token = set_current_organization(stashed.organization)

        return stashed

    def process_exception(self, request: HttpRequest, exception: BaseException) -> None:
        self._unbind_organization(request)

    def process_response(self, request: HttpRequest, response: HttpResponseBase) -> HttpResponseBase:
        self._unbind_organization(request)
        return response

    def _unbind_organization(self, request: HttpRequest) -> None:
        """Restore the organization bound before this request, exactly once."""
        stashed = cast('OrganizationRequest', request)
        token: OrganizationToken | None = getattr(request, '_organization_token', None)

        if token is not None:
            del stashed._organization_token
            reset_current_organization(token)

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        request = self.process_request(request)

        try:
            response = self.get_response(request)
        except Exception as exception:
            self.process_exception(request, exception)
            raise

        return self.process_response(request, response)
