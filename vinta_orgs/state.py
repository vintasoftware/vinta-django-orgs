"""Typed access to the organization bound to the current execution context.

Applications specialize :class:`OrganizationState` once, alongside their
services, so every state operation preserves the swapped organization type::

    class ProjectOrganizationState(OrganizationState[ProjectOrganization]):
        model_class = ProjectOrganization

    organization_state = ProjectOrganizationState()

The value is stored in a :class:`contextvars.ContextVar`, making it isolated per
thread and per async task. The storage primitives are private and model-
agnostic so Django can import model mixins without a circular import.
"""

from __future__ import annotations

import threading
from contextlib import ContextDecorator
from types import TracebackType
from typing import Generic, Literal, Self, TypeVar, cast

from django.utils.functional import LazyObject, SimpleLazyObject

from vinta_orgs._state import OrganizationToken, bind_organization, get_bound_organization, reset_organization
from vinta_orgs.conf import get_organization_model
from vinta_orgs.models import AbstractOrganization, Organization

_OrganizationT = TypeVar('_OrganizationT', bound=AbstractOrganization)


class OrganizationState(Generic[_OrganizationT]):
    """Context state bound to one concrete organization model."""

    model_class: type[AbstractOrganization] = Organization

    __slots__ = ('_organization_model',)

    def __init__(self) -> None:
        if type(self) is OrganizationState:
            configured_model = get_organization_model()
        else:
            configured_model = get_organization_model(self.model_class)
        self._organization_model = cast('type[_OrganizationT]', configured_model)

    @property
    def model(self) -> type[_OrganizationT]:
        """The configured organization model, retaining its concrete type."""
        return self._organization_model

    def _get_by_slug(self, slug: str) -> _OrganizationT | None:
        return self.model._default_manager.filter(slug=slug).first()

    def _coerce(self, organization: _OrganizationT | LazyObject | str | None) -> AbstractOrganization | None:
        if organization is None or isinstance(organization, LazyObject):
            # A LazyObject bound here promises to stand in for this state's
            # organization type. Keeping it lazy is why request binding costs
            # no query until scoped data is actually read.
            return cast('AbstractOrganization | None', organization)

        if isinstance(organization, str):
            return cast(
                'AbstractOrganization',
                SimpleLazyObject(lambda: self._get_by_slug(organization)),
            )

        if not isinstance(organization, self.model):
            raise TypeError(
                "OrganizationState expects '%s', not '%s'" % (self.model._meta.label, organization._meta.label)
            )
        return organization

    def get(self) -> _OrganizationT | None:
        """Return the organization currently bound to this context."""
        organization = get_bound_organization()
        if organization is None:
            return None
        if isinstance(organization, LazyObject):
            if not organization:
                return None
            if not isinstance(organization, self.model):
                raise TypeError("The lazy organization does not resolve to '%s'" % self.model._meta.label)
            return organization
        if not isinstance(organization, self.model):
            raise TypeError(
                "The current organization is '%s', not '%s'" % (organization._meta.label, self.model._meta.label)
            )
        return organization

    def set(self, organization: _OrganizationT | LazyObject | str | None) -> OrganizationToken:
        """Bind an organization, lazy organization, slug, or ``None``."""
        return bind_organization(self._coerce(organization))

    def clear(self) -> OrganizationToken:
        """Unbind the current organization."""
        return bind_organization(None)

    def reset(self, token: OrganizationToken) -> None:
        """Restore the organization that was bound before ``token``."""
        reset_organization(token)

    def context(
        self,
        organization: _OrganizationT | LazyObject | str | None,
    ) -> OrganizationContext[_OrganizationT]:
        """Bind ``organization`` for a block or decorated callable."""
        return OrganizationContext(self, organization)


class OrganizationContext(ContextDecorator, Generic[_OrganizationT]):
    """A nestable context manager created by :meth:`OrganizationState.context`."""

    def __init__(
        self,
        state: OrganizationState[_OrganizationT],
        organization: _OrganizationT | LazyObject | str | None,
    ) -> None:
        self.state = state
        self.organization = organization
        self._local = threading.local()

    @property
    def _tokens(self) -> list[OrganizationToken]:
        tokens: list[OrganizationToken] | None = getattr(self._local, 'tokens', None)
        if tokens is None:
            tokens = self._local.tokens = []
        return tokens

    def _recreate_cm(self) -> Self:
        return self.__class__(self.state, self.organization)

    def __enter__(self) -> _OrganizationT | None:
        self._tokens.append(self.state.set(self.organization))
        return self.state.get()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        self.state.reset(self._tokens.pop())
        return False


organization_state: OrganizationState[AbstractOrganization] = OrganizationState()
"""Package-internal state following the currently configured swapped model."""
