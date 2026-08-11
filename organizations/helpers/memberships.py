from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, cast

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import Group, Permission
from django.db import transaction

from organizations.models import OrganizationMembership

if TYPE_CHECKING:
    from organizations.models import Organization


def create_membership(
    organization: Organization,
    user: AbstractBaseUser,
    groups: Iterable[Group] | None = None,
    permissions: Iterable[Permission] | None = None,
) -> OrganizationMembership:
    groups = groups if groups is not None else []
    permissions = permissions if permissions is not None else []

    with transaction.atomic():
        # ``cast`` because ``AUTH_USER_MODEL`` is the project's choice, while the
        # type checker only sees the one this repository's settings point at.
        membership = OrganizationMembership.objects.create(user=cast('Any', user), organization=organization)
        for group in groups:
            membership.groups.add(group)
        for perm in permissions:
            membership.permissions.add(perm)

        return membership
