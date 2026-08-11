from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from organizations.auth_backends import OrganizationModelBackend
from organizations.helpers.organizations import get_current_organization
from organizations_custom_data.models import (
    OrganizationSpecificTablesPermission,
    OrganizationSpecificTablesRelationship,
)

if TYPE_CHECKING:
    from django.db.models import Model, QuerySet

    from organizations.auth_backends import AnyUser
    from organizations.models import Organization


class OrganizationSpecificTablesBackend(OrganizationModelBackend):
    def _get_user_organization_specific_tables_permissions(
        self, relationship: OrganizationSpecificTablesRelationship
    ) -> QuerySet[OrganizationSpecificTablesPermission]:
        return relationship.permissions.all()

    def _get_group_organization_specific_tables_permissions(
        self, relationship: OrganizationSpecificTablesRelationship
    ) -> QuerySet[OrganizationSpecificTablesPermission]:
        relationship_groups_field = OrganizationSpecificTablesRelationship._meta.get_field('groups')
        relationship_groups_query = 'groups__%s' % relationship_groups_field.related_query_name()
        return OrganizationSpecificTablesPermission.objects.filter(**{relationship_groups_query: relationship})

    def _get_relationship(
        self, user_obj: AnyUser, organization: Organization
    ) -> OrganizationSpecificTablesRelationship | None:
        """Return this user's relationship to ``organization``, at most one query per organization.

        ``_get_organization_specific_tables_permissions`` is called once for
        ``user`` and once for ``group`` permissions, and both need the same row;
        without this cache every permission check fetched it twice.
        """
        cache = self._get_organization_cache(user_obj, '_organization_specific_tables_relationship_cache')

        if organization.pk not in cache:
            cache[organization.pk] = OrganizationSpecificTablesRelationship.objects.filter(
                user=user_obj, organization=organization
            ).first()

        relationship: OrganizationSpecificTablesRelationship | None = cache[organization.pk]
        return relationship

    def _get_organization_specific_tables_permissions(
        self, user_obj: AnyUser, obj: Model | None, from_name: str
    ) -> set[str]:
        if not user_obj.is_active or user_obj.is_anonymous or obj is not None:
            return set()

        organization = get_current_organization()
        if not organization:
            return set()

        # The inherited helper keeps the ``{organization_pk: permissions}``
        # cache and updates it in place. Assigning a fresh dictionary here threw
        # away every other organization the user had already been checked
        # against, so anyone moving between two of them re-queried both.
        cache = self._get_organization_cache(user_obj, '_organization_specific_tables_%s_perm_cache' % from_name)

        # ``not in`` rather than a truthiness check: a user with no permissions
        # in this organization caches an empty set, and a falsy check reads that
        # hit as a miss -- which made every ``has_perm`` the user does *not*
        # have re-run the query, on every call.
        if organization.pk not in cache:
            # Either a ``values_list`` of codenames or an empty set, so the
            # annotation names what the two branches have in common.
            relationship_perms: Iterable[str]

            if user_obj.is_superuser:
                relationship_perms = (
                    OrganizationSpecificTablesPermission.objects.all().values_list('codename', flat=True).order_by()
                )
            else:
                relationship = self._get_relationship(user_obj, organization)

                if relationship is None:
                    relationship_perms = set()
                else:
                    permissions = getattr(self, '_get_%s_organization_specific_tables_permissions' % from_name)(
                        relationship
                    )
                    relationship_perms = permissions.values_list('codename', flat=True).order_by()

            cache[organization.pk] = set(relationship_perms)

        permissions_for_organization: set[str] = cache[organization.pk]
        return permissions_for_organization

    def get_user_organization_specific_tables_permissions(
        self, user_obj: AnyUser, obj: Model | None = None
    ) -> set[str]:
        return self._get_organization_specific_tables_permissions(user_obj, obj, 'user')

    def get_group_organization_specific_tables_permissions(
        self, user_obj: AnyUser, obj: Model | None = None
    ) -> set[str]:
        return self._get_organization_specific_tables_permissions(user_obj, obj, 'group')

    def get_all_organization_specific_table_permissions(self, user_obj: AnyUser, obj: Model | None = None) -> set[str]:
        if not user_obj.is_active or user_obj.is_anonymous or obj is not None:
            return set()

        organization = get_current_organization()
        if not organization:
            return set()

        # Through the inherited helper rather than assigning the attribute
        # directly: it is the same ``{organization_pk: permissions}`` cache the
        # other permission lookups keep, and it updates in place instead of
        # replacing the whole dictionary, so a user moving between two
        # organizations no longer drops the one they just left.
        cache = self._get_organization_cache(user_obj, '_organization_specific_tables_perm_cache')

        # ``not in``, not a truthiness check: an empty permission set is an
        # answer, and treating it as a miss re-ran both lookups every time.
        if organization.pk not in cache:
            cache[organization.pk] = self.get_user_organization_specific_tables_permissions(user_obj, obj).union(
                self.get_group_organization_specific_tables_permissions(user_obj, obj)
            )

        permissions: set[str] = cache[organization.pk]
        return permissions

    def has_perm(self, user_obj: AnyUser, perm: str, obj: Model | None = None) -> bool:
        if isinstance(perm, str):
            return perm in self.get_all_organization_specific_table_permissions(user_obj, obj)

        if not user_obj.is_active:
            return False
        return perm in self.get_all_permissions(user_obj, obj)
