from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import Permission
from django.db.models import Q, QuerySet

from organizations.helpers.organizations import get_current_organization
from organizations.models import OrganizationMembership

if TYPE_CHECKING:
    from django.db.models import Model

    from organizations.models import Organization


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

    def _get_user_organization_permissions(self, membership: OrganizationMembership) -> QuerySet[Permission]:
        return membership.permissions.all()

    def _get_group_organization_permissions(self, membership: OrganizationMembership) -> QuerySet[Permission]:
        membership_groups_field = OrganizationMembership._meta.get_field('groups')
        membership_groups_query = 'group__%s' % membership_groups_field.related_query_name()
        return Permission.objects.filter(**{membership_groups_query: membership})

    def _get_user_permissions(self, membership: OrganizationMembership) -> QuerySet[Permission]:
        membership_permissions_field = OrganizationMembership._meta.get_field('permissions')
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

    def _get_group_permissions(self, membership: OrganizationMembership) -> QuerySet[Permission]:
        membership_groups_field = OrganizationMembership._meta.get_field('groups')
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

    def _get_membership(self, user_obj: AnyUser, organization: Organization) -> OrganizationMembership | None:
        """Return this user's membership in ``organization``, at most one query per organization.

        ``_get_organization_permissions`` is called once for ``user`` and once
        for ``group`` permissions, and each call needs the same membership row;
        without this cache every permission check paid for both.
        """
        cache = self._get_organization_cache(user_obj, '_organization_membership_cache')

        if organization.pk not in cache:
            cache[organization.pk] = (
                OrganizationMembership.objects.filter_by_organization(organization).filter(user=user_obj).first()
            )

        membership: OrganizationMembership | None = cache[organization.pk]
        return membership

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

            if membership_perms is None:
                cache[organization.pk] = set()
            else:
                cache[organization.pk] = {
                    '%s.%s' % (ct, name)
                    for ct, name in membership_perms.values_list('content_type__app_label', 'codename').order_by()
                }

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
