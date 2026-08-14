"""Type-safe organization and membership operations.

Applications bind their swapped models once by subclassing these services and
declaring ``model_class``. Every operation then preserves that concrete type::

    class Organizations(OrganizationService[ProjectOrganization]):
        model_class = ProjectOrganization

    class Memberships(
        MembershipService[ProjectOrganization, ProjectOrganizationMembership]
    ):
        model_class = ProjectOrganizationMembership

The base classes follow Django's configured models dynamically. Their declared
defaults document the models used when the two swappable settings are left at
their defaults; subclasses validate their declaration against those settings.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Generic, TypeVar, cast

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import Group, Permission
from django.contrib.sites.models import Site
from django.core.exceptions import ImproperlyConfigured
from django.db import models, transaction

from vinta_orgs.conf import get_organization_membership_model, get_organization_model
from vinta_orgs.exceptions import AmbiguousOrganizationError, OrganizationAccessDeniedError
from vinta_orgs.models import (
    AbstractOrganization,
    AbstractOrganizationMembership,
    Organization,
    OrganizationMembership,
    OrganizationSite,
)
from vinta_orgs.resolution import UNRESOLVED_ORGANIZATION, OrganizationSelection
from vinta_orgs.settings import get_setting

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from vinta_orgs.auth_backends import AnyUser

_OrganizationT = TypeVar('_OrganizationT', bound=AbstractOrganization)
_OrganizationMembershipT = TypeVar('_OrganizationMembershipT', bound=AbstractOrganizationMembership)


class OrganizationService(Generic[_OrganizationT]):
    """Operations for one concrete organization model.

    Subclasses set :attr:`model_class` and need no constructor arguments. The
    unspecialized base class is reserved for package internals and resolves the
    active swapped model directly, which keeps the package itself compatible
    with every project configuration.
    """

    model_class: type[AbstractOrganization] = Organization

    __slots__ = ('_organization_model',)

    def __init__(self) -> None:
        if type(self) is OrganizationService:
            configured_model = get_organization_model()
        else:
            configured_model = get_organization_model(self.model_class)

        # Django settings are a runtime boundary. The checked class declaration
        # above is the evidence that lets the public methods retain the generic
        # type chosen by the subclass.
        self._organization_model = cast('type[_OrganizationT]', configured_model)

    @property
    def model(self) -> type[_OrganizationT]:
        """The configured organization model, retaining its concrete type."""
        return self._organization_model

    def require_instance(self, organization: AbstractOrganization) -> _OrganizationT:
        """Validate and narrow an organization received at an external boundary."""
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
        """Create an organization and its optional initial owner membership."""
        with transaction.atomic():
            organization = self.model._default_manager.create(name=name, slug=slug)

            for domain in domains or ():
                site = Site.objects.create(name=name, domain=domain)
                OrganizationSite.original_manager.create(organization_id=organization.pk, site=site)

            if user is not None:
                membership_service: MembershipService[_OrganizationT, AbstractOrganizationMembership] = (
                    MembershipService()
                )
                membership = membership_service.create(organization, user)
                membership.groups.add(self.create_default_groups()[0])

            return organization

    def update(
        self,
        organization: _OrganizationT,
        name: str | None = None,
        slug: str | None = None,
    ) -> _OrganizationT:
        """Update the fields supplied for an organization."""
        self.require_instance(organization)

        with transaction.atomic():
            organization.name = name if name else organization.name
            organization.slug = slug if slug else organization.slug
            organization.save()
            return organization

    def create_default_groups(self) -> list[Group]:
        """Create the package's default organization roles, idempotently."""
        with transaction.atomic():
            group, created = Group.objects.get_or_create(name='organization_owner')

            if created:
                for permission_name in get_setting('DEFAULT_ORGANIZATION_OWNER_PERMISSIONS'):
                    app_label, codename = permission_name.split('.', 1)
                    try:
                        permission = Permission.objects.get(
                            content_type__app_label=app_label,
                            codename=codename,
                        )
                    except Permission.DoesNotExist:
                        continue
                    group.permissions.add(permission)

            return [group]


class MembershipService(Generic[_OrganizationT, _OrganizationMembershipT]):
    """Operations for a membership model and its related organization model.

    Only ``model_class`` is declared. The organization model is derived from
    that model's ``organization`` foreign key and checked against
    ``ORGANIZATION_MODEL``, preventing the two service types from drifting
    apart at runtime.
    """

    model_class: type[AbstractOrganizationMembership] = OrganizationMembership

    __slots__ = ('_membership_model', '_organization_model')

    def __init__(self) -> None:
        if type(self) is MembershipService:
            configured_model = get_organization_membership_model()
        else:
            configured_model = get_organization_membership_model(self.model_class)

        organization_field = configured_model._meta.get_field('organization')
        configured_organization_model = get_organization_model()
        if (
            not isinstance(organization_field, models.ForeignKey)
            or organization_field.related_model is not configured_organization_model
        ):
            raise ImproperlyConfigured(
                '%s.organization must target the configured organization model (%s)'
                % (configured_model._meta.label, configured_organization_model._meta.label)
            )

        # These are the two runtime-to-static boundaries. Both values were
        # checked against Django's configured models immediately above.
        self._membership_model = cast('type[_OrganizationMembershipT]', configured_model)
        self._organization_model = cast('type[_OrganizationT]', configured_organization_model)

    @property
    def model(self) -> type[_OrganizationMembershipT]:
        """The configured membership model, retaining its concrete type."""
        return self._membership_model

    @property
    def organization_model(self) -> type[_OrganizationT]:
        """The organization model targeted by :attr:`model_class`."""
        return self._organization_model

    def require_organization(self, organization: AbstractOrganization) -> _OrganizationT:
        """Validate and narrow an organization received at an external boundary."""
        if not isinstance(organization, self.organization_model):
            raise TypeError(
                "MembershipService expects organization '%s', not '%s'"
                % (self.organization_model._meta.label, organization._meta.label)
            )
        return organization

    @staticmethod
    def _cache_relation(instance: models.Model, field_name: str, value: models.Model) -> None:
        """Cache a relation after an ID-based write, preserving object identity."""
        field = instance._meta.get_field(field_name)
        if not isinstance(field, models.ForeignKey):
            raise TypeError('%s.%s must be a ForeignKey' % (instance._meta.label, field_name))
        field.set_cached_value(instance, value)

    def create(
        self,
        organization: _OrganizationT,
        user: AbstractBaseUser,
        groups: Iterable[Group] | None = None,
        permissions: Iterable[Permission] | None = None,
    ) -> _OrganizationMembershipT:
        """Create a membership and attach its initial grants."""
        organization = self.require_organization(organization)

        with transaction.atomic():
            membership = self.model._default_manager.create(
                user_id=user.pk,
                organization_id=organization.pk,
            )
            if not isinstance(membership, self.model):
                raise TypeError(
                    "The membership manager returned '%s', not '%s'" % (membership._meta.label, self.model._meta.label)
                )
            # ID-based kwargs support arbitrary swapped model classes. Restore
            # the object caches that instance-valued kwargs would populate.
            self._cache_relation(membership, 'user', user)
            self._cache_relation(membership, 'organization', organization)

            for group in groups or ():
                membership.groups.add(group)
            for permission in permissions or ():
                membership.permissions.add(permission)

            return membership

    def get_active(self, user: AnyUser) -> QuerySet[_OrganizationMembershipT]:
        """Return ``user``'s active memberships, oldest first."""
        return (
            self.model._default_manager.filter(user_id=user.pk, is_active=True)
            .select_related('organization')
            .order_by('created')
        )

    def resolve_for_user(
        self,
        user: AnyUser | None,
        slug: OrganizationSelection = None,
        *,
        strict: bool = True,
    ) -> _OrganizationMembershipT | None:
        """Resolve a caller-controlled selection through active memberships.

        With no selection, zero memberships resolves to ``None``, one resolves
        to that row, and multiple raise :class:`AmbiguousOrganizationError`.
        A supplied selection that is unavailable raises
        :class:`OrganizationAccessDeniedError`. ``strict=False`` converts both
        refusal cases to ``None``.
        """
        if user is None or user.is_anonymous or not user.is_active:
            return None

        if slug is UNRESOLVED_ORGANIZATION:
            if strict:
                raise OrganizationAccessDeniedError()
            return None

        memberships = self.get_active(user)

        if slug:
            membership = memberships.filter(organization__slug=slug).first()
            if membership is None and strict:
                raise OrganizationAccessDeniedError()
            return membership

        candidates = list(memberships[:2])
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1 and strict:
            raise AmbiguousOrganizationError()
        return None

    def resolve_organization_for_user(
        self,
        user: AnyUser | None,
        slug: OrganizationSelection = None,
        *,
        strict: bool = True,
    ) -> _OrganizationT | None:
        """Resolve only the organization side of a caller's membership."""
        membership = self.resolve_for_user(user, slug, strict=strict)
        if membership is None:
            return None

        organization = membership.organization
        if not isinstance(organization, self.organization_model):
            raise TypeError(
                "The resolved organization is '%s', not '%s'"
                % (organization._meta.label, self.organization_model._meta.label)
            )
        return organization
