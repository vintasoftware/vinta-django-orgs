"""One way to ask "may this user do X **in organization Y**".

``user.has_perm('app.codename')`` cannot answer that question. It answers a
different one -- "may this user do X, given whatever organization happens to be
bound, plus everything they hold globally, unless they are a superuser in which
case yes" -- and the two agree often enough that reaching for ``has_perm`` looks
right until it is not. Three ways it is not:

*The organization is ambient.* ``ModelBackend`` resolves organization
permissions from :func:`vinta_orgs.state.get_current_organization`, so it can
only answer about the bound one. A permission class asking about an *ancestor*
organization (reseller billing), and a DRF view that binds nothing at all
because it never went through the middleware, both get an answer to a question
they did not ask.

*The global half.* ``has_perm`` unions in ``user.user_permissions`` and the
user's own ``auth.Group`` rows. Neither is scoped to an organization, so one
grant made once in the Django admin -- or membership of a global group whose
name happens to match an organization role -- becomes a grant in every
organization in the database.

*The superuser short-circuit.* ``PermissionsMixin.has_perm`` returns ``True``
for a superuser before any backend runs.

:func:`has_organization_permission` asks the *organization* half alone, resolved
from an **active** membership in the organization named. Both widening sources
are parameters, and both default to off. Where you want ``ModelBackend``
semantics -- the Django admin, ``DjangoModelPermissions`` -- keep using
``has_perm``; it is unchanged.

Three shapes of the same question live here, for the three shapes of caller:

* :func:`has_organization_permission` takes a ``(user, organization)`` pair, and
  is what a permission class asks;
* :func:`membership_holds_permission` takes a membership row the caller already
  holds;
* :func:`resolve_membership_permissions` answers for a whole page of memberships
  at once, which is what an API that publishes them needs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from django.db.models import prefetch_related_objects
from django.utils.functional import LazyObject

from vinta_orgs.conf import get_organization_membership_model, get_organization_model
from vinta_orgs.querysets import filter_memberships_holding_permission
from vinta_orgs.state import get_current_organization, organization_context

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.contrib.auth.models import Permission

    from vinta_orgs.auth_backends import AnyUser
    from vinta_orgs.models import AbstractOrganization, AbstractOrganizationMembership


def _organization_by_pk(organization_pk: Any) -> AbstractOrganization | None:
    """Load the organization to bind when the caller only had its primary key."""
    organization: AbstractOrganization | None = (
        get_organization_model()._default_manager.filter(pk=organization_pk).first()
    )
    return organization


def get_organization_permissions(
    user: AnyUser | None,
    organization: AbstractOrganization | Any,
    *,
    include_global: bool = False,
    allow_superuser: bool = False,
) -> set[str]:
    """Every ``'app_label.codename'`` ``user`` holds in ``organization``.

    ``organization`` may be an ``Organization`` or its primary key; the primary
    key form costs one extra query, and only when the organization asked about
    is not the one already bound.

    The organization is bound for the duration of the lookup and the previous
    binding restored afterwards. The resolution itself takes the organization as
    an argument and does not depend on the binding -- the binding is for
    everything *underneath*, which is written against the ambient organization:
    the membership manager, and any future change to how a membership is looked
    up. When the organization asked about is already the bound one, that costs
    nothing at all.

    See :meth:`vinta_orgs.auth_backends.OrganizationModelBackend.get_organization_permissions`
    for what ``include_global`` and ``allow_superuser`` admit, and why neither is
    the default.
    """
    if user is None or user.is_anonymous or not user.is_active or organization is None:
        return set()

    # ``hasattr(..., 'pk')`` rather than an ``isinstance`` check: callers pass an
    # ``Organization``, a ``LazyObject`` standing in for one (which proxies
    # ``pk``), or a bare primary key -- which is not always an ``int``.
    target: AbstractOrganization | None
    organization_pk: Any

    if hasattr(organization, 'pk'):
        target = cast('AbstractOrganization', organization)
        organization_pk = target.pk
    elif isinstance(organization, LazyObject):
        # A lazy stand-in that resolved to nothing. The middleware binds one of
        # those whenever no retriever recognized the request, and
        # ``request.organization`` is what a permission class passes in, so this
        # arrives here rather than as a plain ``None``.
        return set()
    else:
        target = None
        organization_pk = organization

    if organization_pk is None:
        return set()

    current = get_current_organization()

    # ``getattr`` rather than ``current.pk``: the bound value may be a
    # ``SimpleLazyObject`` standing in for an organization that does not exist,
    # which has no ``pk``.
    if current is not None and str(getattr(current, 'pk', None)) == str(organization_pk):
        return _resolve(user, current, include_global=include_global, allow_superuser=allow_superuser)

    if target is None:
        target = _organization_by_pk(organization_pk)

    if target is None:
        return set()

    with organization_context(target):
        return _resolve(user, target, include_global=include_global, allow_superuser=allow_superuser)


def _resolve(
    user: AnyUser,
    organization: AbstractOrganization,
    *,
    include_global: bool,
    allow_superuser: bool,
) -> set[str]:
    """Ask the backend, with the organization already bound.

    A fresh backend instance per call is free: the class holds no state, and
    every cache it fills lives on the ``user`` object, so a second call reuses
    the first one's cached sets. Instantiated directly rather than picked out of
    ``get_backends()`` because this asks *this* backend a question the
    ``AUTHENTICATION_BACKENDS`` protocol does not define -- there is no other
    entry that could answer it. A project with its own subclass calls that
    subclass's ``get_organization_permissions`` directly.
    """
    from vinta_orgs.auth_backends import OrganizationModelBackend

    return OrganizationModelBackend().get_organization_permissions(
        user, organization, include_global=include_global, allow_superuser=allow_superuser
    )


def has_organization_permission(
    user: AnyUser | None,
    permission: str,
    organization: AbstractOrganization | Any,
    *,
    include_global: bool = False,
    allow_superuser: bool = False,
) -> bool:
    """Whether ``user`` holds ``permission`` through an active membership in ``organization``.

    ``permission`` is an ``'app_label.codename'`` string, the same spelling
    ``has_perm`` takes::

        from vinta_orgs.authorization import has_organization_permission

        class IsOrganizationAdmin(BasePermission):
            def has_permission(self, request, view):
                return has_organization_permission(
                    request.user, 'organizations.manage_members', request.organization
                )

    Returns ``False`` for an anonymous caller, an inactive user, an organization
    that does not exist and a caller with no active membership in it -- so a
    resolved-or-``None`` organization can be passed straight in without a guard
    at the call site.
    """
    return permission in get_organization_permissions(
        user, organization, include_global=include_global, allow_superuser=allow_superuser
    )


def membership_holds_permission(membership: AbstractOrganizationMembership, permission: str) -> bool:
    """Whether **this membership row** carries ``permission``.

    The membership-shaped sibling of :func:`has_organization_permission`, for
    the call sites whose question is about a row they already hold rather than
    about a ``(user, organization)`` pair.

    Deliberately not implemented in terms of :func:`has_organization_permission`
    even though the two agree wherever both are defined. That one takes a user,
    and so applies the backend's ``user.is_active`` gate and needs
    ``membership.user`` loaded; this one asks only about the row. It does apply
    the membership's own ``is_active`` gate, because an inactive membership
    grants nothing anywhere else either.

    One query, and no predicate of its own: it is
    :meth:`vinta_orgs.querysets.OrganizationMembershipQuerySet.holding_permission`
    narrowed to a single row, so it cannot drift from what a last-administrator
    guard counts.

    **The membership must be saved.** The lookup is by primary key, so an
    unsaved row filters on ``pk=None``, matches nothing, and answers ``False`` --
    indistinguishable from a real refusal. Documented rather than enforced,
    because a caller building memberships in memory has to assign groups and
    save before the question means anything at all.
    """
    memberships = get_organization_membership_model()._default_manager.filter(pk=membership.pk, is_active=True)
    return filter_memberships_holding_permission(memberships, permission).exists()


def resolve_membership_permissions(
    memberships: Iterable[AbstractOrganizationMembership],
) -> dict[Any, list[str]]:
    """``{membership pk: sorted permission labels}`` for a whole page of memberships.

    The batch read of exactly what
    :meth:`vinta_orgs.auth_backends.OrganizationModelBackend.get_organization_permissions`
    resolves one pair at a time: the union of each membership's direct
    ``permissions`` grant with the permissions its ``groups`` carry, with
    neither the global half nor the superuser short-circuit -- so what an API
    publishes as a member's capabilities is what the permission classes will
    actually honour.

    **Why not just call the backend N times.** It answers one
    ``(user, organization)`` pair and caches per organization on the *user*
    object, so a page of N memberships is N lookups -- the shape anyone exposing
    memberships over an API hits on their first list endpoint. This walks
    prefetched relations instead, so the query count is constant in N.

    ``prefetch_related_objects`` fills the caches on the instances the caller
    already holds, and skips any relation already fetched, so a caller that
    remembered the ``prefetch_related`` pays nothing for calling this and one
    that forgot still gets a constant number of queries.

    An inactive membership, and a membership whose user is inactive, resolve the
    empty list -- the backend's two gates, restated so a page containing such a
    row cannot report capabilities the backend refuses.
    """
    rows = list(memberships)

    if not rows:
        return {}

    prefetch_related_objects(rows, 'user', 'permissions__content_type', 'groups__permissions__content_type')

    resolved: dict[Any, list[str]] = {}

    for membership in rows:
        if not membership.is_active or not membership.user.is_active:
            resolved[membership.pk] = []
            continue

        labels = {_permission_label(permission) for permission in membership.permissions.all()}

        for group in membership.groups.all():
            labels |= {_permission_label(permission) for permission in group.permissions.all()}

        resolved[membership.pk] = sorted(labels)

    return resolved


def _permission_label(permission: Permission) -> str:
    """``'app_label.codename'`` -- the same spelling the backend's sets use."""
    return '%s.%s' % (permission.content_type.app_label, permission.codename)
