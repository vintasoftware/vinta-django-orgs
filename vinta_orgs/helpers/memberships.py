from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Final, TypeAlias

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import Group, Permission
from django.db import models, transaction

from vinta_orgs.conf import get_organization_membership_model
from vinta_orgs.exceptions import AmbiguousOrganizationError, OrganizationAccessDeniedError

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from vinta_orgs.auth_backends import AnyUser
    from vinta_orgs.models import AbstractOrganization, AbstractOrganizationMembership


class _UnresolvedOrganization:
    """Type of the public unresolved-organization singleton."""

    __slots__ = ()

    def __repr__(self) -> str:
        return 'UNRESOLVED_ORGANIZATION'


UNRESOLVED_ORGANIZATION: Final = _UnresolvedOrganization()
"""A caller supplied an organization identifier that matched no organization."""

OrganizationSelection: TypeAlias = 'str | _UnresolvedOrganization | None'


def _cache_relation(instance: models.Model, field_name: str, value: models.Model) -> None:
    """Cache a relation value after an ID-based write, preserving object identity."""
    field = instance._meta.get_field(field_name)
    if not isinstance(field, models.ForeignKey):
        raise TypeError('%s.%s must be a ForeignKey' % (instance._meta.label, field_name))
    field.set_cached_value(instance, value)


def create_membership(
    organization: AbstractOrganization,
    user: AbstractBaseUser,
    groups: Iterable[Group] | None = None,
    permissions: Iterable[Permission] | None = None,
) -> AbstractOrganizationMembership:
    groups = groups if groups is not None else []
    permissions = permissions if permissions is not None else []

    with transaction.atomic():
        membership = get_organization_membership_model()._default_manager.create(
            user_id=user.pk,
            organization_id=organization.pk,
        )
        # ID-based kwargs keep this helper compatible with arbitrary swapped
        # model classes. Restore the object caches an instance-valued create
        # would have populated, so callers observe the exact user and
        # organization instances they supplied.
        _cache_relation(membership, 'user', user)
        _cache_relation(membership, 'organization', organization)
        for group in groups:
            membership.groups.add(group)
        for perm in permissions:
            membership.permissions.add(perm)

        return membership


def get_active_memberships(user: AnyUser) -> QuerySet[AbstractOrganizationMembership]:
    """``user``'s active memberships, oldest first, with the organization fetched.

    The organization switcher's query, and the one
    :func:`resolve_membership_for_user` reads.
    """
    memberships: QuerySet[AbstractOrganizationMembership] = (
        get_organization_membership_model()
        ._default_manager.filter(user_id=user.pk, is_active=True)
        .select_related('organization')
        .order_by('created')
    )
    return memberships


def resolve_membership_for_user(
    user: AnyUser | None,
    slug: OrganizationSelection = None,
    *,
    strict: bool = True,
) -> AbstractOrganizationMembership | None:
    """Which organization is this request for? -- answered from memberships, not from trust.

    ``slug`` is what the caller named, if anything: the value of the
    organization header, a query parameter, a form field. It is
    **caller-controlled**, which is the whole reason this function exists. The
    naive resolution -- look the slug up and select it -- lets any authenticated
    user select any tenant by typing its slug, and every organization-scoped
    manager in the process then happily serves that tenant's rows.

    The full table, which is what makes the ambiguous cases decidable rather
    than a coin flip:

    ==================  ==============================  =====================================
    Active memberships  ``slug``                        Result
    ==================  ==============================  =====================================
    any                 -- anonymous / ``None`` user    ``None``
    any                 names one of them               that membership
    any                 names anything else             ``OrganizationAccessDeniedError``
    0                   absent                          ``None``
    1                   absent                          that membership
    2+                  absent                          ``AmbiguousOrganizationError``
    ==================  ==============================  =====================================

    The 2+/absent row is the one worth arguing about. Picking a membership --
    the oldest, say -- means the request reads and writes an organization the
    caller never named, chosen by row creation order; a user who administers an
    old organization A and is a plain member of B passes an administrator gate
    for a request that then serves B. Refusing is the only answer that cannot be
    wrong, and the caller fixes it by naming one.

    A slug naming an organization the caller is not an active member of is
    refused rather than ignored, and refused identically whether the
    organization does not exist, the caller has no membership in it, or the
    membership is deactivated. Answering those three differently would turn this
    into an oracle for which slugs are taken.

    ``strict=False`` turns both refusals into ``None``. That is for the handful
    of endpoints that must serve a caller who has not selected an organization
    yet -- the organization switcher itself, onboarding, an invitation accept --
    not a default to reach for. Everything downstream then sees no organization
    bound, which under ``STRICT_ORGANIZATION_FILTER`` is a loud failure rather
    than a quiet cross-tenant read.
    """
    if user is None or user.is_anonymous or not user.is_active:
        return None

    if slug is UNRESOLVED_ORGANIZATION:
        if strict:
            raise OrganizationAccessDeniedError()
        return None

    memberships = get_active_memberships(user)

    if slug:
        membership = memberships.filter(organization__slug=slug).first()

        if membership is None and strict:
            raise OrganizationAccessDeniedError()

        return membership

    # Two rows are all it takes to tell "exactly one" from "more than one", and
    # the switcher's own listing is a different query with a different budget.
    candidates = list(memberships[:2])

    if len(candidates) == 1:
        return candidates[0]

    if len(candidates) > 1 and strict:
        raise AmbiguousOrganizationError()

    return None


def resolve_organization_for_user(
    user: AnyUser | None,
    slug: OrganizationSelection = None,
    *,
    strict: bool = True,
) -> AbstractOrganization | None:
    """The organization half of :func:`resolve_membership_for_user`.

    Same table, same refusals; use this when the membership row itself is of no
    interest.
    """
    membership = resolve_membership_for_user(user, slug, strict=strict)
    return membership.organization if membership is not None else None
