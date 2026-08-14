"""Storage for the organization the current execution context is bound to.

The value lives in a :class:`contextvars.ContextVar` instead of a
``{thread_id: organization}`` dictionary. A ``ContextVar`` is isolated per
context, which means it works unchanged under ASGI (where several requests
share a thread but each gets its own context) and it cannot leak an
organization from one request into the next when a WSGI worker thread is
reused. It also removes the dictionary that grew one entry per thread id and
was only ever cleaned up on the happy path.

Nothing in here imports models at module level, so it is safe to import from
managers, mixins and the middleware without creating an import cycle.
"""

from __future__ import annotations

import threading
from contextlib import ContextDecorator
from contextvars import ContextVar, Token
from types import TracebackType
from typing import TYPE_CHECKING, Generic, Literal, Self, TypeAlias, TypeVar, cast, overload

from django.utils.functional import LazyObject, SimpleLazyObject

if TYPE_CHECKING:
    from vinta_orgs.models import AbstractOrganization

_OrganizationT = TypeVar('_OrganizationT', bound='AbstractOrganization')

#: What callers may bind: a loaded ``Organization``, the slug of one, or a
#: ``LazyObject`` standing in for one -- which is what the middleware binds so
#: a request that never reads it pays no query.
OrganizationOrSlug: TypeAlias = 'AbstractOrganization | LazyObject | str'

#: The token :func:`set_current_organization` hands back, which
#: :func:`reset_current_organization` consumes.
OrganizationToken: TypeAlias = 'Token[AbstractOrganization | None]'

_current_organization: ContextVar[AbstractOrganization | None] = ContextVar(
    'vinta_orgs.current_organization', default=None
)


def _get_organization_by_slug(slug: str) -> AbstractOrganization | None:
    from vinta_orgs.conf import get_organization_model

    return get_organization_model()._default_manager.filter(slug=slug).first()


def _coerce_organization(organization: OrganizationOrSlug | None) -> AbstractOrganization | None:
    """Normalize what callers pass into something storable.

    A slug is wrapped in a ``SimpleLazyObject`` so binding an organization
    costs no query until something actually reads it -- a request that never
    touches organization-scoped data pays nothing.
    """
    if organization is None or isinstance(organization, LazyObject):
        # Checked before the ``str`` test below and not merged into it:
        # ``isinstance`` matches a ``LazyObject`` on its concrete type, but any
        # other check falls back to the proxied ``__class__`` and resolves the
        # wrapper -- which would make binding the middleware's lazy organization
        # query on every request, used or not.
        #
        # The cast is what the wrapper promises: a ``LazyObject`` bound here
        # stands in for an ``Organization`` and proxies every attribute to one.
        return cast('AbstractOrganization | None', organization)

    if not isinstance(organization, str):
        return organization

    return cast('AbstractOrganization', SimpleLazyObject(lambda: _get_organization_by_slug(organization)))


@overload
def get_current_organization(expected_type: type[_OrganizationT]) -> _OrganizationT | None: ...


@overload
def get_current_organization(expected_type: None = None) -> AbstractOrganization | None: ...


def get_current_organization(
    expected_type: type[AbstractOrganization] | None = None,
) -> AbstractOrganization | None:
    """Return the bound organization, optionally checked against a concrete type."""
    if expected_type is not None:
        from vinta_orgs.conf import get_organization_model

        get_organization_model(expected_type)

    organization = _current_organization.get()

    if organization is not None and expected_type is not None and not isinstance(organization, expected_type):
        raise TypeError(
            "The current organization is '%s', not an instance of the expected model '%s'"
            % (organization._meta.label, expected_type._meta.label)
        )

    return organization


def set_current_organization(organization: OrganizationOrSlug | None) -> OrganizationToken:
    """Bind ``organization`` (an ``Organization``, a slug or ``None``) to this context.

    Returns the :class:`contextvars.Token` that restores the previous value
    through :func:`reset_current_organization`. Prefer
    :class:`organization_context` when the binding has a well defined scope.
    """
    return _current_organization.set(_coerce_organization(organization))


def clear_current_organization() -> OrganizationToken:
    """Unbind the current organization.

    Unlike a ``del`` on a thread map this is a no-op when nothing is bound, so
    teardown code never has to guard the call.
    """
    return _current_organization.set(None)


def reset_current_organization(token: OrganizationToken) -> None:
    """Restore the organization that was bound before ``token`` was issued."""
    _current_organization.reset(token)


class organization_context(ContextDecorator, Generic[_OrganizationT]):
    """Bind an organization for a block of code, then restore the previous one.

    Usable as a context manager or as a decorator, which is what makes
    organization-scoped code reachable outside the request/response cycle --
    Celery tasks, management commands and tests::

        with organization_context('acme'):
            Article.objects.count()

        @organization_context(organization)
        def rebuild_index():
            ...

    Nested and sequential uses restore the *previous* organization rather than
    clearing it, so a block never silently unscopes its caller.
    """

    @overload
    def __init__(self: organization_context[_OrganizationT], organization: _OrganizationT) -> None: ...

    @overload
    def __init__(self: organization_context[AbstractOrganization], organization: LazyObject | str | None) -> None: ...

    def __init__(self, organization: OrganizationOrSlug | None) -> None:
        self.organization = organization
        self._local = threading.local()

    @property
    def _tokens(self) -> list[OrganizationToken]:
        # Per-thread token stack: tokens are only valid in the context that
        # created them, so one shared list would break under concurrency.
        tokens: list[OrganizationToken] | None = getattr(self._local, 'tokens', None)
        if tokens is None:
            tokens = self._local.tokens = []
        return tokens

    def _recreate_cm(self) -> Self:
        # Called once per invocation of a decorated function, so recursive
        # calls each get their own instance instead of sharing a token stack.
        return self.__class__(self.organization)

    def __enter__(self) -> _OrganizationT | None:
        self._tokens.append(set_current_organization(self.organization))
        # The constructor overloads establish the invariant: an instance input
        # binds its own concrete type, while slugs, lazy values and ``None``
        # instantiate ``organization_context[AbstractOrganization]``.
        return cast('_OrganizationT | None', get_current_organization())

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        reset_current_organization(self._tokens.pop())
        return False
