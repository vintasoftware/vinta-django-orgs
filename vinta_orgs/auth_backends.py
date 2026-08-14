from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import Permission
from django.db.models import Q, QuerySet

from vinta_orgs.conf import get_organization_membership_model
from vinta_orgs.helpers.organizations import get_current_organization

if TYPE_CHECKING:
    from django.db.models import Model

    from vinta_orgs.models import AbstractOrganization, AbstractOrganizationMembership


class AnyUser(Protocol):
    """What the permission lookups here need of a user object.

    Structural rather than a concrete class on purpose. ``ModelBackend`` works
    with any ``AUTH_USER_MODEL`` carrying ``PermissionsMixin``, and with
    ``AnonymousUser``, which is not a model at all -- there is no single base
    class covering both. ``AbstractBaseUser``, which is what django-stubs types
    these arguments as, does not declare ``is_superuser`` or
    ``user_permissions``; a project whose user model genuinely lacks them
    cannot use this backend.
    """

    @property
    def pk(self) -> Any: ...
    @property
    def is_active(self) -> bool: ...
    @property
    def is_anonymous(self) -> bool: ...
    @property
    def is_superuser(self) -> bool: ...
    @property
    def user_permissions(self) -> Any: ...


UserModel = get_user_model()

logger = logging.getLogger(__name__)


class OrganizationModelBackend(ModelBackend):
    """
    Authenticates against settings.AUTH_USER_MODEL.
    """

    def _get_user_global_permissions(self, user_obj: AnyUser) -> QuerySet[Permission]:
        permissions: QuerySet[Permission] = user_obj.user_permissions.all()
        return permissions

    def _get_group_global_permissions(self, user_obj: AnyUser) -> QuerySet[Permission]:
        user_groups_field = get_user_model()._meta.get_field('groups')
        user_groups_query = 'group__%s' % user_groups_field.related_query_name()
        return Permission.objects.filter(**{user_groups_query: user_obj})

    def _get_user_organization_permissions(self, membership: AbstractOrganizationMembership) -> QuerySet[Permission]:
        return membership.permissions.all()

    def _get_group_organization_permissions(self, membership: AbstractOrganizationMembership) -> QuerySet[Permission]:
        membership_groups_field = membership._meta.get_field('groups')
        membership_groups_query = 'group__%s' % membership_groups_field.related_query_name()
        return Permission.objects.filter(**{membership_groups_query: membership})

    def _get_user_permissions(self, membership: AbstractOrganizationMembership) -> QuerySet[Permission]:
        membership_permissions_field = membership._meta.get_field('permissions')
        membership_permission_query = membership_permissions_field.related_query_name()

        user_permissions_field = UserModel._meta.get_field('user_permissions')
        user_permission_query = user_permissions_field.related_query_name()

        user_groups_field = get_user_model()._meta.get_field('groups')
        user_groups_query = 'group__%s' % user_groups_field.related_query_name()
        return Permission.objects.filter(
            Q(**{membership_permission_query: membership})
            | Q(**{user_permission_query: membership.user})
            | Q(**{user_groups_query: membership.user})
        ).distinct()

    def _get_group_permissions(self, membership: AbstractOrganizationMembership) -> QuerySet[Permission]:
        membership_groups_field = membership._meta.get_field('groups')
        membership_groups_query = 'group__%s' % membership_groups_field.related_query_name()
        user_groups_field = get_user_model()._meta.get_field('groups')
        user_groups_query = 'group__%s' % user_groups_field.related_query_name()
        return Permission.objects.filter(
            Q(**{membership_groups_query: membership}) | Q(**{user_groups_query: membership.user})
        )

    def _get_organization_cache(self, user_obj: AnyUser, cache_name: str) -> dict[Any, Any]:
        """Return the ``{organization_pk: value}`` cache named ``cache_name``.

        The cache is keyed by organization and *updated* in place. It used to be
        replaced wholesale on every miss, so a user moving between two
        organizations -- the normal case for anyone with more than one
        membership -- re-queried both every time instead of building up.
        """
        cache: dict[Any, Any] | None = getattr(user_obj, cache_name, None)

        if cache is None:
            cache = {}
            setattr(user_obj, cache_name, cache)

        return cache

    def _get_membership(
        self, user_obj: AnyUser, organization: AbstractOrganization
    ) -> AbstractOrganizationMembership | None:
        """Return this user's *active* membership in ``organization``, at most one query per organization.

        ``_get_organization_permissions`` is called once for ``user`` and once
        for ``group`` permissions, and each call needs the same membership row;
        without this cache every permission check paid for both.

        ``is_active=True`` is part of the lookup rather than a filter applied to
        its result, so the cache holds ``None`` for a deactivated member and
        nothing downstream can reach a row it is not allowed to use. A
        deactivated administrator resolves exactly what a non-member resolves:
        nothing.
        """
        cache = self._get_organization_cache(user_obj, '_organization_membership_cache')

        if organization.pk not in cache:
            cache[organization.pk] = (
                get_organization_membership_model()
                ._default_manager.filter_by_organization(organization)
                .filter(user=user_obj, is_active=True)
                .first()
            )

        membership: AbstractOrganizationMembership | None = cache[organization.pk]
        return membership

    @staticmethod
    def _labelled(permissions: QuerySet[Permission]) -> set[str]:
        """``{'app_label.codename'}`` -- the shape ``has_perm`` compares against."""
        return {
            '%s.%s' % (app_label, codename)
            for app_label, codename in permissions.values_list('content_type__app_label', 'codename').order_by()
        }

    def _get_organization_permissions(self, user_obj: AnyUser, obj: Model | None, from_name: str) -> set[str]:
        if not user_obj.is_active or user_obj.is_anonymous or obj is not None:
            return set()

        organization = get_current_organization()
        if not organization:
            return set()

        cache = self._get_organization_cache(user_obj, '_organization_%s_perm_cache' % from_name)

        # ``not in`` rather than a truthiness check: a user with no permissions
        # in this organization caches an empty set, and the old check treated
        # that hit as a miss and re-ran the query on every call.
        if organization.pk not in cache:
            membership_perms: QuerySet[Permission] | None

            if user_obj.is_superuser:
                membership_perms = Permission.objects.all()
            else:
                membership = self._get_membership(user_obj, organization)

                if membership is None:
                    membership_perms = None
                else:
                    membership_perms = getattr(self, '_get_%s_organization_permissions' % from_name)(membership)

            cache[organization.pk] = set() if membership_perms is None else self._labelled(membership_perms)

        permissions: set[str] = cache[organization.pk]
        return permissions

    def _get_global_permissions(self, user_obj: AnyUser, obj: Model | None, from_name: str) -> set[str]:
        if not user_obj.is_active or user_obj.is_anonymous or obj is not None:
            return set()

        perm_cache_name = '_%s_perm_cache' % from_name
        if not hasattr(user_obj, perm_cache_name):
            perms: QuerySet[Permission]
            if user_obj.is_superuser:
                perms = Permission.objects.all()
            else:
                perms = getattr(self, '_get_%s_global_permissions' % from_name)(user_obj)
            labelled = perms.values_list('content_type__app_label', 'codename').order_by()
            setattr(user_obj, perm_cache_name, {'%s.%s' % (ct, name) for ct, name in labelled})
        permissions: set[str] = getattr(user_obj, perm_cache_name)
        return permissions

    def _get_permissions(self, user_obj: AnyUser, obj: Model | None, from_name: str) -> set[str]:
        return self._get_global_permissions(user_obj, obj, from_name).union(
            self._get_organization_permissions(user_obj, obj, from_name)
        )

    def get_user_global_permissions(self, user_obj: AnyUser, obj: Model | None = None) -> set[str]:
        return self._get_global_permissions(user_obj, obj, 'user')

    def get_user_organization_permissions(self, user_obj: AnyUser, obj: Model | None = None) -> set[str]:
        return self._get_organization_permissions(user_obj, obj, 'user')

    def get_group_global_permissions(self, user_obj: AnyUser, obj: Model | None = None) -> set[str]:
        return self._get_global_permissions(user_obj, obj, 'group')

    def get_group_organization_permissions(self, user_obj: AnyUser, obj: Model | None = None) -> set[str]:
        return self._get_organization_permissions(user_obj, obj, 'group')

    def get_all_global_permissions(self, user_obj: AnyUser, obj: Model | None = None) -> set[str]:
        if not user_obj.is_active or user_obj.is_anonymous or obj is not None:
            return set()
        # Stashed on the user object the way ``_get_global_permissions`` above
        # does it: the cache hangs off an instance that knows nothing about it.
        perm_cache_name = '_perm_cache'

        if not hasattr(user_obj, perm_cache_name):
            # ``union`` rather than ``update``: the two calls return the cached
            # sets themselves, so updating one in place polluted the per-source
            # cache with the other source's permissions.
            setattr(
                user_obj,
                perm_cache_name,
                self.get_user_global_permissions(user_obj, obj).union(
                    self.get_group_global_permissions(user_obj, obj)
                ),
            )

        permissions: set[str] = getattr(user_obj, perm_cache_name)
        return permissions

    def get_all_organization_permissions(self, user_obj: AnyUser, obj: Model | None = None) -> set[str]:
        if not user_obj.is_active or user_obj.is_anonymous or obj is not None:
            return set()

        organization = get_current_organization()
        if not organization:
            return set()

        cache = self._get_organization_cache(user_obj, '_organization_perm_cache')

        if organization.pk not in cache:
            cache[organization.pk] = self.get_user_organization_permissions(user_obj, obj).union(
                self.get_group_organization_permissions(user_obj, obj)
            )

        permissions: set[str] = cache[organization.pk]
        return permissions

    def get_all_permissions(self, user_obj: AnyUser, obj: Model | None = None) -> set[str]:
        return self.get_all_global_permissions(user_obj, obj).union(
            self.get_all_organization_permissions(user_obj, obj)
        )

    def _get_membership_permissions(self, user_obj: AnyUser, organization: AbstractOrganization) -> set[str]:
        """The permissions ``user_obj`` holds through an active membership in ``organization``.

        The union of the membership's own ``permissions`` grant with the
        permissions its ``groups`` carry, and nothing else. Cached by
        organization pk on the user object, the same way -- and through the same
        helper as -- every other cache in this backend, so asking about a second
        organization neither re-queries the first nor poisons its entry.
        """
        cache = self._get_organization_cache(user_obj, '_organization_membership_perm_cache')

        if organization.pk not in cache:
            membership = self._get_membership(user_obj, organization)

            if membership is None:
                cache[organization.pk] = set()
            else:
                cache[organization.pk] = self._labelled(
                    self._get_user_organization_permissions(membership)
                ) | self._labelled(self._get_group_organization_permissions(membership))

        permissions: set[str] = cache[organization.pk]
        return permissions

    def get_organization_permissions(
        self,
        user_obj: AnyUser,
        organization: AbstractOrganization | None,
        *,
        include_global: bool = False,
        allow_superuser: bool = False,
    ) -> set[str]:
        """What ``user_obj`` may do **in ``organization``** -- named, not ambient.

        Every other permission entry point on this backend reads the
        organization from the context, so it can only answer about whichever one
        happens to be bound. That is the wrong shape for the question almost
        every call site actually asks: "is this user an administrator" is a
        statement about a *particular* membership's organization. Two shapes of
        call site cannot express it any other way -- one that asks about an
        organization other than the bound one (an ancestor, for reseller
        billing), and one that binds nothing at all (a DRF view outside the
        middleware's reach). Both get a confidently wrong answer from
        ``has_perm``.

        The two sources that *widen* the answer are parameters here rather than
        built in, because both are privilege escalations when this question is
        the one being asked, and both default to off:

        ``include_global``
            ``user.user_permissions`` plus the user's own global ``auth.Group``
            rows. Neither is scoped to an organization, so a single grant made
            once in the Django admin becomes a grant in *every* organization at
            once.

        ``allow_superuser``
            The short-circuit that answers ``Permission.objects.all()`` without
            consulting any membership. A superuser reading every tenant through
            the Django admin is one thing; a superuser passing a gate that
            charges a customer's card because they are nominally a member of the
            organization is another.

        ``has_perm`` keeps ``ModelBackend`` semantics exactly -- superuser
        passes, global grants union in -- because that is what the Django admin
        and every ``ModelBackend`` consumer expect of it. This method is an
        addition, not an override: nothing in ``ModelBackend`` reaches it.

        Prefer :func:`vinta_orgs.authorization.has_organization_permission`,
        which wraps this and also binds ``organization`` for the duration of the
        check, so anything underneath that still reads the ambient organization
        sees the one being asked about.
        """
        if organization is None or user_obj.is_anonymous or not user_obj.is_active:
            return set()

        if allow_superuser and user_obj.is_superuser:
            return self._labelled(Permission.objects.all())

        permissions = self._get_membership_permissions(user_obj, organization)

        if include_global:
            # ``get_all_global_permissions`` applies the superuser
            # short-circuit to the *global* half, which is where it belongs:
            # asking for the global half is asking for ``ModelBackend``'s
            # answer, and that is what ``ModelBackend`` answers.
            permissions = permissions | self.get_all_global_permissions(user_obj)

        return permissions
