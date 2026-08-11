from typing import Any

from django.contrib.auth.models import Permission, User
from django.test import TestCase

from organizations.auth_backends import OrganizationModelBackend
from organizations.helpers.memberships import create_membership
from organizations.helpers.organizations import (
    clear_current_organization,
    create_default_organization_groups,
    set_current_organization,
)
from organizations.models import Organization, OrganizationMembership


def group_permission_count(membership: OrganizationMembership) -> int:
    """How many permissions the membership's first group carries."""
    group = membership.groups.first()
    assert group is not None
    return int(group.permissions.count())


def perm_cache(user: User, cache_name: str) -> dict[Any, set[str]]:
    """One of the ``{organization_pk: permissions}`` caches the backend stashes on ``user``.

    Read through ``getattr`` because that is how the backend writes it: the
    cache hangs off a user object that declares nothing about it.
    """
    cache: dict[Any, set[str]] = getattr(user, cache_name)
    return cache


class OrganizationModelBackendTests(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name='test', slug='test')
        set_current_organization(self.organization.slug)
        self.user = User.objects.create_user(
            first_name='test',
            last_name='test',
            username='test',
            email='test@sharedschemaorganizations.com',
            password='test',
        )
        self.membership = create_membership(self.organization, self.user, groups=create_default_organization_groups())

    def test__get_group_organization_permissions(self) -> None:
        set_current_organization(self.organization.slug)
        auth_backend = OrganizationModelBackend()
        self.assertEqual(
            len(auth_backend._get_organization_permissions(self.user, None, 'group')),
            group_permission_count(self.membership),
        )
        self.assertEqual(
            len(perm_cache(self.user, '_organization_group_perm_cache')[self.organization.pk]),
            group_permission_count(self.membership),
        )

    def test__get_user_organization_permissions(self) -> None:
        set_current_organization(self.organization.slug)
        auth_backend = OrganizationModelBackend()
        self.assertEqual(
            len(auth_backend._get_organization_permissions(self.user, None, 'user')),
            self.membership.permissions.count(),
        )
        self.assertEqual(
            len(perm_cache(self.user, '_organization_user_perm_cache')[self.organization.pk]),
            self.membership.permissions.count(),
        )

    def test__get_permissions(self) -> None:
        set_current_organization(self.organization.slug)
        auth_backend = OrganizationModelBackend()
        self.assertEqual(
            len(auth_backend._get_permissions(self.user, None, 'group')),
            group_permission_count(self.membership),
        )

    def test_get_all_organization_permissions(self) -> None:
        set_current_organization(self.organization.slug)
        auth_backend = OrganizationModelBackend()
        self.assertEqual(
            len(auth_backend.get_all_organization_permissions(self.user)),
            group_permission_count(self.membership),
        )
        self.assertEqual(
            len(perm_cache(self.user, '_organization_perm_cache')[self.organization.pk]),
            group_permission_count(self.membership),
        )

    def test_get_all_permissions(self) -> None:
        set_current_organization(self.organization.slug)
        auth_backend = OrganizationModelBackend()
        self.assertEqual(len(auth_backend.get_all_permissions(self.user)), group_permission_count(self.membership))
        self.assertEqual(
            len(perm_cache(self.user, '_organization_perm_cache')[self.organization.pk]),
            group_permission_count(self.membership),
        )

    def test__get_user_permissions(self) -> None:
        set_current_organization(self.organization.slug)
        auth_backend = OrganizationModelBackend()
        self.assertEqual(len(auth_backend._get_user_permissions(self.membership)), self.membership.permissions.count())

    def test__get_group_permissions(self) -> None:
        set_current_organization(self.organization.slug)
        auth_backend = OrganizationModelBackend()
        self.assertEqual(
            len(auth_backend._get_group_permissions(self.membership)),
            group_permission_count(self.membership),
        )

    def test__get_group_organization_permissions_with_superuser(self) -> None:
        set_current_organization(self.organization.slug)
        self.user.is_superuser = True
        self.user.save()
        auth_backend = OrganizationModelBackend()
        self.assertEqual(
            len(auth_backend._get_organization_permissions(self.user, None, 'group')), Permission.objects.all().count()
        )
        self.assertEqual(
            len(perm_cache(self.user, '_organization_group_perm_cache')[self.organization.pk]),
            Permission.objects.all().count(),
        )

    def test__get_user_organization_permissions_with_superuser(self) -> None:
        set_current_organization(self.organization.slug)
        self.user.is_superuser = True
        self.user.save()
        auth_backend = OrganizationModelBackend()
        self.assertEqual(
            len(auth_backend._get_organization_permissions(self.user, None, 'user')), Permission.objects.all().count()
        )
        self.assertEqual(
            len(perm_cache(self.user, '_organization_user_perm_cache')[self.organization.pk]),
            Permission.objects.all().count(),
        )

    def test__get_permissions_with_superuser(self) -> None:
        set_current_organization(self.organization.slug)
        self.user.is_superuser = True
        self.user.save()
        auth_backend = OrganizationModelBackend()
        self.assertEqual(
            len(auth_backend._get_permissions(self.user, None, 'group')), Permission.objects.all().count()
        )

    def test_get_all_organization_permissions_with_superuser(self) -> None:
        set_current_organization(self.organization.slug)
        self.user.is_superuser = True
        self.user.save()
        auth_backend = OrganizationModelBackend()
        self.assertEqual(
            len(auth_backend.get_all_organization_permissions(self.user)), Permission.objects.all().count()
        )
        self.assertEqual(
            len(perm_cache(self.user, '_organization_perm_cache')[self.organization.pk]),
            Permission.objects.all().count(),
        )

    def test_get_all_permissions_with_superuser(self) -> None:
        set_current_organization(self.organization.slug)
        self.user.is_superuser = True
        self.user.save()
        auth_backend = OrganizationModelBackend()
        self.assertEqual(len(auth_backend.get_all_permissions(self.user)), Permission.objects.all().count())
        self.assertEqual(
            len(perm_cache(self.user, '_organization_perm_cache')[self.organization.pk]),
            Permission.objects.all().count(),
        )

    def test__get_group_organization_permissions_without_organization(self) -> None:
        clear_current_organization()
        auth_backend = OrganizationModelBackend()
        self.assertEqual(len(auth_backend._get_organization_permissions(self.user, None, 'group')), 0)

    def test__get_user_organization_permissions_without_organization(self) -> None:
        clear_current_organization()
        auth_backend = OrganizationModelBackend()
        self.assertEqual(len(auth_backend._get_organization_permissions(self.user, None, 'user')), 0)

    def test__get_permissions_without_organization(self) -> None:
        clear_current_organization()
        auth_backend = OrganizationModelBackend()
        self.assertEqual(len(auth_backend._get_permissions(self.user, None, 'group')), 0)

    def test_get_all_organization_permissions_without_organization(self) -> None:
        clear_current_organization()
        auth_backend = OrganizationModelBackend()
        self.assertEqual(len(auth_backend.get_all_organization_permissions(self.user)), 0)

    def test__get_group_organization_permissions_without_active_user(self) -> None:
        set_current_organization(self.organization.slug)
        self.user.is_active = False
        self.user.save()
        auth_backend = OrganizationModelBackend()
        self.assertEqual(len(auth_backend._get_organization_permissions(self.user, None, 'group')), 0)

    def test__get_user_organization_permissions_without_active_user(self) -> None:
        set_current_organization(self.organization.slug)
        self.user.is_active = False
        self.user.save()
        auth_backend = OrganizationModelBackend()
        self.assertEqual(len(auth_backend._get_organization_permissions(self.user, None, 'user')), 0)

    def test__get_permissions_without_active_user(self) -> None:
        set_current_organization(self.organization.slug)
        self.user.is_active = False
        self.user.save()
        auth_backend = OrganizationModelBackend()
        self.assertEqual(len(auth_backend._get_permissions(self.user, None, 'group')), 0)

    def test_get_all_organization_permissions_without_active_user(self) -> None:
        set_current_organization(self.organization.slug)
        self.user.is_active = False
        self.user.save()
        auth_backend = OrganizationModelBackend()
        self.assertEqual(len(auth_backend.get_all_organization_permissions(self.user)), 0)

    def test_get_all_permissions_without_active_user(self) -> None:
        set_current_organization(self.organization.slug)
        self.user.is_active = False
        self.user.save()
        auth_backend = OrganizationModelBackend()
        self.assertEqual(len(auth_backend.get_all_permissions(self.user)), 0)

    def test__get_group_organization_permissions_without_user_in_organization(self) -> None:
        set_current_organization(self.organization.slug)
        self.user.memberships.all().delete()
        auth_backend = OrganizationModelBackend()
        self.assertEqual(len(auth_backend._get_organization_permissions(self.user, None, 'group')), 0)

    def test__get_user_organization_permissions_without_user_in_organization(self) -> None:
        set_current_organization(self.organization.slug)
        self.user.memberships.all().delete()
        auth_backend = OrganizationModelBackend()
        self.assertEqual(len(auth_backend._get_organization_permissions(self.user, None, 'user')), 0)

    def test__get_permissions_without_user_in_organization(self) -> None:
        set_current_organization(self.organization.slug)
        self.user.memberships.all().delete()
        auth_backend = OrganizationModelBackend()
        self.assertEqual(len(auth_backend._get_permissions(self.user, None, 'group')), 0)

    def test_get_all_organization_permissions_without_user_in_organization(self) -> None:
        set_current_organization(self.organization.slug)
        self.user.memberships.all().delete()
        auth_backend = OrganizationModelBackend()
        self.assertEqual(len(auth_backend.get_all_organization_permissions(self.user)), 0)


class OrganizationPermissionCacheTests(TestCase):
    """The per-organization caches have to survive an organization switch.

    Permission lookups happen on every request, so a cache that is rebuilt
    instead of extended -- or one that reads an empty result as a miss -- turns
    into queries on the hottest path there is.
    """

    def setUp(self) -> None:
        self.organization_1 = Organization.objects.create(name='one', slug='one')
        self.organization_2 = Organization.objects.create(name='two', slug='two')
        set_current_organization(self.organization_1)

        self.user = User.objects.create_user(username='test', password='test')
        groups = create_default_organization_groups()
        self.membership_1 = create_membership(self.organization_1, self.user, groups=groups)
        self.membership_2 = create_membership(self.organization_2, self.user, groups=groups)
        self.auth_backend = OrganizationModelBackend()

    def tearDown(self) -> None:
        clear_current_organization()

    def test_permissions_are_cached_per_organization(self) -> None:
        set_current_organization(self.organization_1)
        self.auth_backend.get_all_organization_permissions(self.user)

        with self.assertNumQueries(0):
            self.auth_backend.get_all_organization_permissions(self.user)

    def test_switching_back_to_an_organization_reuses_its_cache(self) -> None:
        set_current_organization(self.organization_1)
        self.auth_backend.get_all_organization_permissions(self.user)

        set_current_organization(self.organization_2)
        self.auth_backend.get_all_organization_permissions(self.user)

        set_current_organization(self.organization_1)
        with self.assertNumQueries(0):
            self.auth_backend.get_all_organization_permissions(self.user)

    def test_an_empty_permission_set_is_cached_too(self) -> None:
        self.user.memberships.all().delete()
        set_current_organization(self.organization_1)

        self.auth_backend._get_organization_permissions(self.user, None, 'user')

        with self.assertNumQueries(0):
            self.assertEqual(self.auth_backend._get_organization_permissions(self.user, None, 'user'), set())

    def test_membership_is_looked_up_once_per_organization(self) -> None:
        set_current_organization(self.organization_1)

        # One membership query, then one permission query per source.
        with self.assertNumQueries(3):
            self.auth_backend.get_all_organization_permissions(self.user)

    def test_user_and_group_caches_stay_separate(self) -> None:
        group = self.membership_1.groups.first()
        assert group is not None
        permission = Permission.objects.exclude(id__in=group.permissions.values_list('id', flat=True)).first()
        assert permission is not None
        self.membership_1.permissions.add(permission)
        set_current_organization(self.organization_1)

        self.auth_backend.get_all_organization_permissions(self.user)

        # The union used to be built by mutating the per-source cache in place,
        # which leaked group permissions into the user cache and back.
        self.assertNotIn(
            '%s.%s' % (permission.content_type.app_label, permission.codename),
            perm_cache(self.user, '_organization_group_perm_cache')[self.organization_1.pk],
        )
