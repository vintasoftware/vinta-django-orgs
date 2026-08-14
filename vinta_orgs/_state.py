"""Model-agnostic storage primitives for the organization context.

This module deliberately does not import ``vinta_orgs.models``. Model mixins
and querysets are imported while Django is still defining those models, so
they use these private primitives without creating an import cycle. The public,
typed interface lives in :mod:`vinta_orgs.state`.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    from vinta_orgs.models import AbstractOrganization

OrganizationToken: TypeAlias = 'Token[AbstractOrganization | None]'

_current_organization: ContextVar[AbstractOrganization | None] = ContextVar(
    'vinta_orgs.current_organization', default=None
)


def get_bound_organization() -> AbstractOrganization | None:
    return _current_organization.get()


def bind_organization(organization: AbstractOrganization | None) -> OrganizationToken:
    return _current_organization.set(organization)


def reset_organization(token: OrganizationToken) -> None:
    _current_organization.reset(token)
