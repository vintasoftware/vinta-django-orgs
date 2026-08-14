from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Generic, TypeVar, cast, overload

from django.http import HttpRequest
from django.http.response import HttpResponseBase
from django.utils.functional import SimpleLazyObject

from vinta_orgs._state import OrganizationToken
from vinta_orgs.settings import get_setting
from vinta_orgs.state import organization_state
from vinta_orgs.utils import import_from_string

if TYPE_CHECKING:
    from vinta_orgs.models import AbstractOrganization

_OrganizationT = TypeVar('_OrganizationT', bound='AbstractOrganization')


class OrganizationRequest(HttpRequest, Generic[_OrganizationT]):
    """The request as :class:`OrganizationMiddleware` leaves it.

    Nothing is ever instantiated from this class -- Django builds the request,
    and the middleware attaches the attributes below to whatever it is handed.
    It exists so that ``request.organization`` has a name and a type, both for
    the middleware itself and for the views and helpers a project writes
    against it. Parameterize it with a swapped organization model to retain
    that concrete type::

        def my_view(request: OrganizationRequest[MyOrganization]) -> HttpResponse:
            ...
    """

    #: The organization this request belongs to, resolved on first read.
    organization: _OrganizationT | None
    #: Memoizes :func:`get_organization` for the life of the request.
    _cached_organization: _OrganizationT | None
    #: Whatever was bound before the request started, used as a fallback.
    _organization_before_request: _OrganizationT | None
    #: Restores that previous binding once the response is on its way out.
    _organization_token: OrganizationToken


@overload
def get_organization(request: OrganizationRequest[_OrganizationT]) -> _OrganizationT | None: ...


@overload
def get_organization(request: HttpRequest) -> AbstractOrganization | None: ...


def get_organization(request: HttpRequest) -> AbstractOrganization | None:
    """Resolve the organization this request belongs to, at most once per request."""
    stashed = cast('OrganizationRequest[AbstractOrganization]', request)

    if not hasattr(request, '_cached_organization'):
        stashed._cached_organization = _retrieve_organization(stashed)

    return stashed._cached_organization


def _retrieve_organization(request: OrganizationRequest[AbstractOrganization]) -> AbstractOrganization | None:
    for organization_retriever in get_setting('ORGANIZATION_RETRIEVERS'):
        organization: AbstractOrganization | None = import_from_string(organization_retriever)(request)

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

            return organization

    # No retriever recognized the request. Fall back to whatever was bound to
    # this context *before* the request started -- an organization set by a
    # test, a task or a management command. Reading the binding the middleware
    # itself just installed would recurse, which is why the previous value is
    # stashed on the request instead of read back from the context.
    if hasattr(request, '_organization_before_request'):
        return request._organization_before_request

    return organization_state.get()


class OrganizationMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponseBase]) -> None:
        self.get_response = get_response

    def process_request(self, request: HttpRequest) -> OrganizationRequest[AbstractOrganization]:
        stashed = cast('OrganizationRequest[AbstractOrganization]', request)

        stashed._organization_before_request = organization_state.get()
        stashed.organization = cast('AbstractOrganization', SimpleLazyObject(lambda: get_organization(request)))
        stashed._organization_token = organization_state.set(stashed.organization)

        return stashed

    def process_exception(self, request: HttpRequest, exception: BaseException) -> None:
        self._unbind_organization(request)

    def process_response(self, request: HttpRequest, response: HttpResponseBase) -> HttpResponseBase:
        self._unbind_organization(request)
        return response

    def _unbind_organization(self, request: HttpRequest) -> None:
        """Restore the organization bound before this request, exactly once."""
        stashed = cast('OrganizationRequest[AbstractOrganization]', request)
        token: OrganizationToken | None = getattr(request, '_organization_token', None)

        if token is not None:
            del stashed._organization_token
            organization_state.reset(token)

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        request = self.process_request(request)

        try:
            response = self.get_response(request)
        except Exception as exception:
            self.process_exception(request, exception)
            raise

        return self.process_response(request, response)
