from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, cast

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import Group, Permission
from django.db import transaction

from vinta_orgs.conf import get_organization_membership_model
from vinta_orgs.exceptions import AmbiguousOrganizationError, OrganizationAccessDeniedError

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from vinta_orgs.auth_backends import AnyUser
    from vinta_orgs.models import Organization, OrganizationMembership


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
        membership = get_organization_membership_model()._default_manager.create(
            user=cast('Any', user), organization=organization
        )
        for group in groups:
            membership.groups.add(group)
        for perm in permissions:
            membership.permissions.add(perm)

        return membership


def get_active_memberships(user: AnyUser) -> QuerySet[OrganizationMembership]:
    """``user``'s active memberships, oldest first, with the organization fetched.

    The organization switcher's query, and the one
    :func:`resolve_membership_for_user` reads.
    """
    memberships: QuerySet[OrganizationMembership] = (
        get_organization_membership_model()
        ._default_manager.filter(user=cast('Any', user), is_active=True)
        .select_related('organization')
        .order_by('created')
    )
    return memberships


def resolve_membership_for_user(
    user: AnyUser | None,
    slug: str | None = None,
    *,
    strict: bool = True,
) -> OrganizationMembership | None:
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
    slug: str | None = None,
    *,
    strict: bool = True,
) -> Organization | None:
    """The organization half of :func:`resolve_membership_for_user`.

    Same table, same refusals; use this when the membership row itself is of no
    interest.
    """
    membership = resolve_membership_for_user(user, slug, strict=strict)
    return membership.organization if membership is not None else None
