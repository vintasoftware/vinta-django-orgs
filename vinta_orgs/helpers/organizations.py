from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, cast

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


def create_organization(
    name: str,
    slug: str,
    domains: Iterable[str] | None = None,
    user: AbstractBaseUser | None = None,
) -> AbstractOrganization:
    from vinta_orgs.conf import get_organization_model

    with transaction.atomic():
        organization = get_organization_model()._default_manager.create(name=name, slug=slug)

        for domain in domains or []:
            site = Site.objects.create(name=name, domain=domain)
            cast('Any', organization).organization_sites.create(site=site)

        if user:
            # ``AUTH_USER_MODEL`` is whatever the project installing this app
            # configured; the type checker only ever sees the one this
            # repository's settings point at.
            rel = cast('Any', organization).memberships.create(user=cast('Any', user))
            rel.groups.add(create_default_organization_groups()[0])

        return organization


def update_organization(
    organization: AbstractOrganization, name: str | None = None, slug: str | None = None
) -> AbstractOrganization:
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
