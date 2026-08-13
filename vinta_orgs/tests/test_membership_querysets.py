"""The membership-shaped lookups on the membership queryset.

``holding_permission`` is the one that matters: it is what a last-administrator
guard has to count by once a role is a permission rather than a column, and it
has to agree with what the permission backend resolves or the guard and the gate
disagree about who is an administrator.
"""

from typing import TYPE_CHECKING

from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase

from vinta_orgs.authorization import get_organization_permissions
from vinta_orgs.conf import get_organization_membership_model, get_organization_model
from vinta_orgs.helpers.memberships import create_membership, get_active_memberships
from vinta_orgs.helpers.organizations import clear_current_organization, set_current_organization

if TYPE_CHECKING:
    from vinta_orgs.models import Organization, OrganizationMembership
else:
    Organization = get_organization_model()
    OrganizationMembership = get_organization_membership_model()

MANAGE = 'auth.change_group'


def manage_permission() -> Permission:
    return Permission.objects.get(content_type__app_label='auth', codename='change_group')


class MembershipQuerySetTests(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name='acme', slug='acme')
        self.other_organization = Organization.objects.create(name='globex', slug='globex')
        set_current_organization(self.organization)

        self.admin_user = User.objects.create_user(username='admin', password='x')
        self.direct_user = User.objects.create_user(username='direct', password='x')
        self.plain_user = User.objects.create_user(username='plain', password='x')

        self.admin_group = Group.objects.create(name='org-admins')
        self.admin_group.permissions.add(manage_permission())

        self.admin = create_membership(self.organization, self.admin_user, groups=[self.admin_group])
        self.direct = create_membership(self.organization, self.direct_user, permissions=[manage_permission()])
        self.plain = create_membership(self.organization, self.plain_user)

    def tearDown(self) -> None:
        clear_current_organization()

    def holders(self) -> set[int]:
        return set(
            OrganizationMembership.objects.filter_by_organization(self.organization)
            .holding_permission(MANAGE)
            .values_list('pk', flat=True)
        )

    def test_a_group_grant_counts(self) -> None:
        self.assertIn(self.admin.pk, self.holders())

    def test_a_direct_grant_counts(self) -> None:
        # Over-counting is the safe direction: a guard that missed a member
        # holding the permission directly would clear the last administrator.
        self.assertIn(self.direct.pk, self.holders())

    def test_a_member_holding_neither_does_not(self) -> None:
        self.assertNotIn(self.plain.pk, self.holders())

    def test_a_membership_is_counted_once_however_many_paths_grant_it(self) -> None:
        second_group = Group.objects.create(name='org-admins-too')
        second_group.permissions.add(manage_permission())
        self.admin.groups.add(second_group)
        self.admin.permissions.add(manage_permission())

        holders = (
            OrganizationMembership.objects.filter_by_organization(self.organization)
            .holding_permission(MANAGE)
            .filter(pk=self.admin.pk)
        )

        self.assertEqual(holders.count(), 1)

    def test_a_codename_from_another_app_does_not_satisfy_half_of_it(self) -> None:
        self.assertEqual(
            OrganizationMembership.objects.holding_permission('vinta_orgs.change_group').count(),
            0,
        )

    def test_a_malformed_label_is_an_error_rather_than_an_empty_result(self) -> None:
        with self.assertRaises(ValueError):
            OrganizationMembership.objects.holding_permission('change_group')

    def test_it_agrees_with_what_the_backend_resolves(self) -> None:
        for membership, user in ((self.admin, self.admin_user), (self.direct, self.direct_user), (self.plain, None)):
            holds = membership.pk in self.holders()

            if user is None:
                self.assertFalse(holds)
                continue

            self.assertEqual(holds, MANAGE in get_organization_permissions(user, self.organization))

    def test_it_does_not_read_the_global_half(self) -> None:
        # A global grant makes ``has_perm`` say yes in every organization; the
        # guard must not count it, or one Django-admin grant makes every member
        # look like an administrator of every tenant.
        self.plain_user.user_permissions.add(manage_permission())

        self.assertNotIn(self.plain.pk, self.holders())

    def test_it_is_not_scoped_implicitly(self) -> None:
        elsewhere = create_membership(self.other_organization, self.admin_user, groups=[self.admin_group])

        self.assertIn(
            elsewhere.pk, set(OrganizationMembership.objects.holding_permission(MANAGE).values_list('pk', flat=True))
        )


class ActiveTests(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name='acme', slug='acme')
        self.other_organization = Organization.objects.create(name='globex', slug='globex')
        set_current_organization(self.organization)
        self.user = User.objects.create_user(username='member', password='x')
        self.membership = create_membership(self.organization, self.user)

    def tearDown(self) -> None:
        clear_current_organization()

    def test_active_drops_the_deactivated_rows(self) -> None:
        self.membership.is_active = False
        self.membership.save()

        self.assertEqual(OrganizationMembership.objects.active().count(), 0)

    def test_active_for_user_orders_oldest_first(self) -> None:
        second = create_membership(self.other_organization, self.user)

        self.assertEqual(
            list(OrganizationMembership.objects.active_for_user(self.user)),
            [self.membership, second],
        )

    def test_active_for_user_fetches_the_organization_in_the_same_query(self) -> None:
        memberships = list(OrganizationMembership.objects.active_for_user(self.user))

        with self.assertNumQueries(0):
            self.assertEqual(memberships[0].organization, self.organization)

    def test_the_helper_and_the_queryset_agree(self) -> None:
        create_membership(self.other_organization, self.user)

        self.assertEqual(
            list(get_active_memberships(self.user)),
            list(OrganizationMembership.objects.active_for_user(self.user)),
        )

    def test_the_reverse_accessor_carries_the_methods_too(self) -> None:
        # Django builds ``user.memberships`` from the model's default manager,
        # so the membership lookups have to survive the trip.
        self.assertEqual(self.user.memberships.active().count(), 1)
