from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, TypeVar, overload

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import Group, Permission
from django.contrib.sites.models import Site
from django.db import transaction

from vinta_orgs.settings import get_setting
from vinta_orgs.state import (  # noqa: F401
    clear_current_organization,
    get_current_organization,
    organization_context,
    reset_current_organization,
    set_current_organization,
)

if TYPE_CHECKING:
    from vinta_orgs.models import AbstractOrganization

_OrganizationT = TypeVar('_OrganizationT', bound='AbstractOrganization')


@overload
def create_organization(
    name: str,
    slug: str,
    domains: Iterable[str] | None = None,
    user: AbstractBaseUser | None = None,
    *,
    organization_model: type[_OrganizationT],
) -> _OrganizationT: ...


@overload
def create_organization(
    name: str,
    slug: str,
    domains: Iterable[str] | None = None,
    user: AbstractBaseUser | None = None,
    *,
    organization_model: None = None,
) -> AbstractOrganization: ...


def create_organization(
    name: str,
    slug: str,
    domains: Iterable[str] | None = None,
    user: AbstractBaseUser | None = None,
    *,
    organization_model: type[AbstractOrganization] | None = None,
) -> AbstractOrganization:
    """Create an organization, preserving an optional concrete model witness."""
    from vinta_orgs.conf import get_organization_model
    from vinta_orgs.helpers.memberships import create_membership
    from vinta_orgs.models import OrganizationSite

    with transaction.atomic():
        if organization_model is None:
            configured_model = get_organization_model()
        else:
            configured_model = get_organization_model(organization_model)

        organization = configured_model._default_manager.create(name=name, slug=slug)

        for domain in domains or []:
            site = Site.objects.create(name=name, domain=domain)
            OrganizationSite.original_manager.create(organization_id=organization.pk, site=site)

        if user:
            rel = create_membership(organization, user)
            rel.groups.add(create_default_organization_groups()[0])

        return organization


def update_organization(
    organization: _OrganizationT, name: str | None = None, slug: str | None = None
) -> _OrganizationT:
    with transaction.atomic():
        organization.name = name if name else organization.name
        organization.slug = slug if slug else organization.slug

        organization.save()

        return organization


def create_default_organization_groups() -> list[Group]:
    with transaction.atomic():
        group, created = Group.objects.get_or_create(name='organization_owner')

        if created:
            for perm in get_setting('DEFAULT_ORGANIZATION_OWNER_PERMISSIONS'):
                try:
                    group.permissions.add(
                        Permission.objects.get(content_type__app_label=perm.split('.')[0], codename=perm.split('.')[1])
                    )
                except Permission.DoesNotExist:
                    pass

        return [group]
