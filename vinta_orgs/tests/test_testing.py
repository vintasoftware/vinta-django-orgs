"""The reseed helper, exercised against the flush it exists for.

``TransactionTestCase`` truncates every table on teardown and re-emits
``post_migrate``, which rebuilds content types and permissions but not the rows
a data migration wrote. This is the test that a seeded group survives that --
and the one that fails if the seeder ever stops being idempotent.
"""

from typing import TYPE_CHECKING

from django.contrib.auth.models import Group, User
from django.test import TestCase, TransactionTestCase, override_settings

from vinta_orgs.conf import get_organization_model
from vinta_orgs.helpers.memberships import create_membership
from vinta_orgs.helpers.organizations import clear_current_organization, set_current_organization
from vinta_orgs.testing import (
    SeededOrganizationGroupsMixin,
    organization_group_seeders,
    reseed_organization_groups,
)

if TYPE_CHECKING:
    from vinta_orgs.models import Organization
else:
    Organization = get_organization_model()

_seeder_calls: list[str] = []


def extra_seeder() -> list[Group]:
    _seeder_calls.append('extra')
    group, _ = Group.objects.get_or_create(name='extra-role')
    return [group]


class ReseedTests(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name='acme', slug='acme')
        set_current_organization(self.organization)

    def tearDown(self) -> None:
        clear_current_organization()
        _seeder_calls.clear()

    def test_it_creates_the_seeded_group(self) -> None:
        Group.objects.filter(name='organization_owner').delete()

        reseed_organization_groups()

        self.assertTrue(Group.objects.filter(name='organization_owner').exists())

    def test_the_group_comes_back_with_its_permissions(self) -> None:
        Group.objects.filter(name='organization_owner').delete()

        group = reseed_organization_groups()[0]

        # An empty group is the failure mode that reads as an unrelated 403 in
        # whatever test asserts on a permission next.
        self.assertGreater(group.permissions.count(), 0)

    def test_it_is_idempotent(self) -> None:
        first = reseed_organization_groups()
        second = reseed_organization_groups()

        self.assertEqual([group.pk for group in first], [group.pk for group in second])
        self.assertEqual(Group.objects.filter(name='organization_owner').count(), 1)

    def test_it_does_not_revoke_a_permission_a_test_attached(self) -> None:
        group = reseed_organization_groups()[0]
        added = group.permissions.model.objects.exclude(pk__in=group.permissions.values_list('pk', flat=True)).first()
        assert added is not None
        group.permissions.add(added)

        reseed_organization_groups()

        self.assertIn(added, group.permissions.all())

    def test_the_default_seeder_is_this_library_s(self) -> None:
        self.assertEqual(
            [seeder.__name__ for seeder in organization_group_seeders()],
            ['create_default_organization_groups'],
        )

    @override_settings(
        SHARED_SCHEMA_ORGANIZATIONS={
            'ORGANIZATION_GROUP_SEEDERS': [
                'vinta_orgs.helpers.organizations.create_default_organization_groups',
                'vinta_orgs.tests.test_testing.extra_seeder',
            ]
        }
    )
    def test_a_project_can_add_its_own_seeders(self) -> None:
        groups = reseed_organization_groups()

        self.assertEqual(_seeder_calls, ['extra'])
        self.assertIn('extra-role', [group.name for group in groups])


class FlushSurvivalTests(SeededOrganizationGroupsMixin, TransactionTestCase):
    """The scenario itself, in the test case class that produces it.

    ``TransactionTestCase`` flushes on teardown, so without the mixin the second
    of these two tests -- whichever order they run in -- would find no seeded
    group and build a membership that silently holds nothing.
    """

    def setUp(self) -> None:
        # Bound *before* delegating, because the mixin's ``setUp`` reseeds and
        # this project's ``vinta_orgs_custom_data`` hangs an organization-scoped
        # row off every ``auth.Group`` written. A seeder that needs an
        # organization bound is the caller's to arrange; the library's own does
        # not. ``TransactionTestCase`` does its database work in ``_pre_setup``,
        # which has already run by the time this is called.
        self.organization = Organization.objects.create(name='acme', slug='acme')
        set_current_organization(self.organization)
        super().setUp()

    def tearDown(self) -> None:
        clear_current_organization()

    def assert_membership_holds_something(self, username: str) -> None:
        user = User.objects.create_user(username=username, password='x')
        membership = create_membership(self.organization, user, groups=reseed_organization_groups())
        group = membership.groups.first()

        assert group is not None
        self.assertGreater(group.permissions.count(), 0)

    def test_a_membership_built_here_holds_permissions(self) -> None:
        self.assert_membership_holds_something('first')

    def test_and_so_does_one_built_after_a_flush(self) -> None:
        self.assert_membership_holds_something('second')
