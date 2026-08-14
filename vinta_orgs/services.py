"""Project-level, concretely typed access to the organization helpers.

The module-level helpers retain abstract return types when Django settings are
their only source of model information. Applications can instead configure
these services once with their swapped models and import the service instances
everywhere else, keeping concrete types without repeating model witnesses.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Generic, TypeVar

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ImproperlyConfigured
from django.db import models

from vinta_orgs.conf import get_organization_membership_model, get_organization_model
from vinta_orgs.helpers.memberships import (
    OrganizationSelection,
    create_membership,
    get_active_memberships,
    resolve_membership_for_user,
    resolve_organization_for_user,
)
from vinta_orgs.helpers.organizations import create_organization, update_organization
from vinta_orgs.state import get_current_organization

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from vinta_orgs.auth_backends import AnyUser
    from vinta_orgs.models import AbstractOrganization, AbstractOrganizationMembership

_OrganizationT = TypeVar('_OrganizationT', bound='AbstractOrganization')
_OrganizationMembershipT = TypeVar('_OrganizationMembershipT', bound='AbstractOrganizationMembership')


class OrganizationService(Generic[_OrganizationT]):
    """Organization helpers bound to one concrete swapped model."""

    __slots__ = ('_organization_model',)

    def __init__(self, organization_model: type[_OrganizationT]) -> None:
        self._organization_model = get_organization_model(organization_model)

    @property
    def model(self) -> type[_OrganizationT]:
        """The configured organization model, retaining its concrete type."""
        return self._organization_model

    def require_instance(self, organization: AbstractOrganization) -> _OrganizationT:
        """Validate and narrow an organization received from an external boundary."""
        if not isinstance(organization, self.model):
            raise TypeError(
                "OrganizationService expects '%s', not '%s'" % (self.model._meta.label, organization._meta.label)
            )
        return organization

    def create(
        self,
        name: str,
        slug: str,
        domains: Iterable[str] | None = None,
        user: AbstractBaseUser | None = None,
    ) -> _OrganizationT:
        return create_organization(
            name,
            slug,
            domains,
            user,
            organization_model=self.model,
        )

    def update(
        self,
        organization: _OrganizationT,
        name: str | None = None,
        slug: str | None = None,
    ) -> _OrganizationT:
        return update_organization(organization, name=name, slug=slug)

    def get_current(self) -> _OrganizationT | None:
        return get_current_organization(self.model)

    def resolve_for_user(
        self,
        user: AnyUser | None,
        slug: OrganizationSelection = None,
        *,
        strict: bool = True,
    ) -> _OrganizationT | None:
        return resolve_organization_for_user(
            user,
            slug,
            strict=strict,
            organization_model=self.model,
        )


class MembershipService(Generic[_OrganizationT, _OrganizationMembershipT]):
    """Membership helpers bound to a concrete organization/model pair."""

    __slots__ = ('_membership_model', '_organizations')

    def __init__(
        self,
        organizations: OrganizationService[_OrganizationT],
        membership_model: type[_OrganizationMembershipT],
    ) -> None:
        self._organizations = organizations
        self._membership_model = get_organization_membership_model(membership_model)

        organization_field = self._membership_model._meta.get_field('organization')
        if (
            not isinstance(organization_field, models.ForeignKey)
            or organization_field.related_model is not organizations.model
        ):
            raise ImproperlyConfigured(
                '%s.organization must target the model configured on OrganizationService (%s)'
                % (self._membership_model._meta.label, organizations.model._meta.label)
            )

    @property
    def organizations(self) -> OrganizationService[_OrganizationT]:
        """The organization service defining the accepted organization type."""
        return self._organizations

    @property
    def model(self) -> type[_OrganizationMembershipT]:
        """The configured membership model, retaining its concrete type."""
        return self._membership_model

    def create(
        self,
        organization: _OrganizationT,
        user: AbstractBaseUser,
        groups: Iterable[Group] | None = None,
        permissions: Iterable[Permission] | None = None,
    ) -> _OrganizationMembershipT:
        organization = self.organizations.require_instance(organization)
        return create_membership(
            organization,
            user,
            groups,
            permissions,
            membership_model=self.model,
        )

    def get_active(self, user: AnyUser) -> QuerySet[_OrganizationMembershipT]:
        return get_active_memberships(user, membership_model=self.model)

    def resolve_for_user(
        self,
        user: AnyUser | None,
        slug: OrganizationSelection = None,
        *,
        strict: bool = True,
    ) -> _OrganizationMembershipT | None:
        return resolve_membership_for_user(
            user,
            slug,
            strict=strict,
            membership_model=self.model,
        )
