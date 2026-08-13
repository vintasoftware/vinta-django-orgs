"""The organization-as-an-argument permission entry points.

``has_perm`` answers about the *bound* organization, from the union of the
organization half with a global half, unless the caller is a superuser in which
case it answers yes. Every one of those three is a different answer to the
question ``has_organization_permission`` asks, and each one of them is a
privilege escalation when it differs.
"""

from typing import TYPE_CHECKING

from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase
from django.utils.functional import SimpleLazyObject

from vinta_orgs.authorization import (
    get_organization_permissions,
    has_organization_permission,
    membership_holds_permission,
    resolve_membership_permissions,
)
from vinta_orgs.conf import get_organization_membership_model, get_organization_model
from vinta_orgs.helpers.memberships import create_membership
from vinta_orgs.helpers.organizations import (
    clear_current_organization,
    create_default_organization_groups,
    get_current_organization,
    set_current_organization,
)

if TYPE_CHECKING:
    from vinta_orgs.models import Organization, OrganizationMembership
else:
    Organization = get_organization_model()
    OrganizationMembership = get_organization_membership_model()


def a_permission(codename: str = 'add_group') -> Permission:
    """Any real permission, named so the assertions read."""
    return Permission.objects.get(content_type__app_label='auth', codename=codename)


def label(permission: Permission) -> str:
    return '%s.%s' % (permission.content_type.app_label, permission.codename)


class AuthorizationTestCase(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name='acme', slug='acme')
        self.other_organization = Organization.objects.create(name='globex', slug='globex')
        self.user = User.objects.create_user(username='member', password='member')
        self.permission = a_permission()
        self.membership = create_membership(self.organization, self.user, permissions=[self.permission])
        # Bound throughout, because writing an ``auth.Group`` -- or attaching one
        # to a membership -- fans out to an organization-scoped row through
        # ``vinta_orgs_custom_data``, which needs an organization to write it
        # into. Nothing under test here reads the binding: every function in
        # this module is asked about an organization by name, which is the whole
        # point of it, and several of the tests below name a *different* one.
        set_current_organization(self.organization)

    def tearDown(self) -> None:
        clear_current_organization()

    def owner_group(self) -> Group:
        """The seeded ``organization_owner`` group, with its permissions."""
        return create_default_organization_groups()[0]

    def global_group(self, name: str, permission: Permission) -> Group:
        """A plain ``auth.Group`` on the user, of the kind the admin's picker lists."""
        group = Group.objects.create(name=name)
        group.permissions.add(permission)
        return group


class HasOrganizationPermissionTests(AuthorizationTestCase):
    def test_a_member_holds_what_their_membership_grants(self) -> None:
        self.assertTrue(has_organization_permission(self.user, label(self.permission), self.organization))

    def test_the_answer_is_about_the_organization_named_not_the_bound_one(self) -> None:
        set_current_organization(self.other_organization)

        # The bound organization is one the user has no membership in at all;
        # ``has_perm`` would answer for that one and say no.
        self.assertTrue(has_organization_permission(self.user, label(self.permission), self.organization))

    def test_a_non_member_holds_nothing(self) -> None:
        self.assertFalse(has_organization_permission(self.user, label(self.permission), self.other_organization))

    def test_the_organization_may_be_given_as_a_primary_key(self) -> None:
        self.assertTrue(has_organization_permission(self.user, label(self.permission), self.organization.pk))

    def test_an_organization_that_does_not_exist_is_a_refusal_not_a_crash(self) -> None:
        self.assertFalse(has_organization_permission(self.user, label(self.permission), 10_000))

    def test_no_organization_is_a_refusal(self) -> None:
        self.assertFalse(has_organization_permission(self.user, label(self.permission), None))

    def test_a_lazy_organization_that_resolves_to_nothing_is_a_refusal(self) -> None:
        # What ``request.organization`` is when no retriever recognized the
        # request: a stand-in, not a ``None``, and the thing a permission class
        # passes straight in.
        unresolved = SimpleLazyObject(lambda: None)

        self.assertFalse(has_organization_permission(self.user, label(self.permission), unresolved))

    def test_a_lazy_organization_that_resolves_is_answered_normally(self) -> None:
        lazy = SimpleLazyObject(lambda: self.organization)

        self.assertTrue(has_organization_permission(self.user, label(self.permission), lazy))

    def test_an_anonymous_caller_is_a_refusal(self) -> None:
        self.assertFalse(has_organization_permission(None, label(self.permission), self.organization))

    def test_an_inactive_user_holds_nothing(self) -> None:
        self.user.is_active = False

        self.assertFalse(has_organization_permission(self.user, label(self.permission), self.organization))

    def test_a_deactivated_membership_holds_nothing(self) -> None:
        self.membership.is_active = False
        self.membership.save()

        self.assertFalse(has_organization_permission(self.user, label(self.permission), self.organization))

    def test_the_binding_is_restored_afterwards(self) -> None:
        set_current_organization(self.other_organization)

        has_organization_permission(self.user, label(self.permission), self.organization)

        self.assertEqual(get_current_organization(), self.other_organization)

    def test_asking_about_the_bound_organization_costs_no_extra_query(self) -> None:
        set_current_organization(self.organization)
        has_organization_permission(self.user, label(self.permission), self.organization)

        # Cached on the user object by organization, so the second ask is free
        # -- and the fast path did not have to load the organization again.
        with self.assertNumQueries(0):
            self.assertTrue(has_organization_permission(self.user, label(self.permission), self.organization))


class WideningSourcesTests(AuthorizationTestCase):
    """The two sources that make ``has_perm`` answer a different question."""

    def test_a_global_user_permission_does_not_grant_it_in_an_organization(self) -> None:
        granted = a_permission('delete_group')
        self.user.user_permissions.add(granted)

        # ``has_perm`` says yes -- and would say yes for every organization in
        # the database, from one grant made once in the Django admin.
        self.assertTrue(User.objects.get(pk=self.user.pk).has_perm(label(granted)))
        self.assertFalse(has_organization_permission(self.user, label(granted), self.organization))

    def test_a_global_group_does_not_grant_it_in_an_organization(self) -> None:
        granted = a_permission('delete_group')
        self.user.groups.add(self.global_group('global-admins', granted))

        self.assertFalse(has_organization_permission(self.user, label(granted), self.organization))

    def test_a_superuser_is_answered_from_their_memberships(self) -> None:
        self.user.is_superuser = True
        granted = a_permission('delete_group')

        self.assertFalse(has_organization_permission(self.user, label(granted), self.organization))

    def test_include_global_admits_the_global_half(self) -> None:
        granted = a_permission('delete_group')
        self.user.user_permissions.add(granted)

        self.assertTrue(has_organization_permission(self.user, label(granted), self.organization, include_global=True))

    def test_allow_superuser_admits_the_short_circuit(self) -> None:
        self.user.is_superuser = True

        self.assertTrue(
            has_organization_permission(
                self.user, label(a_permission('delete_group')), self.organization, allow_superuser=True
            )
        )

    def test_allow_superuser_does_nothing_for_an_ordinary_user(self) -> None:
        self.assertFalse(
            has_organization_permission(
                self.user, label(a_permission('delete_group')), self.organization, allow_superuser=True
            )
        )


class GetOrganizationPermissionsTests(AuthorizationTestCase):
    def test_it_returns_the_union_of_the_membership_grant_and_its_groups(self) -> None:
        group = self.owner_group()
        self.membership.groups.add(group)

        expected = {label(self.permission)} | {label(permission) for permission in group.permissions.all()}

        self.assertEqual(get_organization_permissions(self.user, self.organization), expected)

    def test_a_second_organization_neither_re_queries_nor_poisons_the_first(self) -> None:
        create_membership(self.other_organization, self.user)

        first = get_organization_permissions(self.user, self.organization)
        get_organization_permissions(self.user, self.other_organization)

        with self.assertNumQueries(0):
            self.assertEqual(get_organization_permissions(self.user, self.organization), first)


class MembershipHoldsPermissionTests(AuthorizationTestCase):
    def test_a_direct_grant_counts(self) -> None:
        self.assertTrue(membership_holds_permission(self.membership, label(self.permission)))

    def test_a_group_grant_counts(self) -> None:
        group = self.owner_group()
        granted = group.permissions.first()
        assert granted is not None
        self.membership.groups.add(group)

        self.assertTrue(membership_holds_permission(self.membership, label(granted)))

    def test_a_permission_the_membership_does_not_hold_is_refused(self) -> None:
        self.assertFalse(membership_holds_permission(self.membership, label(a_permission('delete_group'))))

    def test_a_deactivated_membership_holds_nothing(self) -> None:
        self.membership.is_active = False
        self.membership.save()

        self.assertFalse(membership_holds_permission(self.membership, label(self.permission)))

    def test_a_malformed_permission_label_is_an_error_not_an_empty_answer(self) -> None:
        with self.assertRaises(ValueError):
            membership_holds_permission(self.membership, 'add_group')


class ResolveMembershipPermissionsTests(AuthorizationTestCase):
    def test_it_agrees_with_the_backend_for_every_membership_shape(self) -> None:
        group = self.owner_group()
        self.membership.groups.add(group)
        plain_user = User.objects.create_user(username='plain', password='plain')
        plain = create_membership(self.organization, plain_user)

        resolved = resolve_membership_permissions([self.membership, plain])

        self.assertEqual(set(resolved[self.membership.pk]), get_organization_permissions(self.user, self.organization))
        self.assertEqual(set(resolved[plain.pk]), get_organization_permissions(plain_user, self.organization))

    def test_a_deactivated_membership_publishes_nothing(self) -> None:
        self.membership.is_active = False
        self.membership.save()

        self.assertEqual(resolve_membership_permissions([self.membership]), {self.membership.pk: []})

    def test_a_deactivated_user_publishes_nothing(self) -> None:
        self.user.is_active = False
        self.user.save()

        self.assertEqual(resolve_membership_permissions([self.membership]), {self.membership.pk: []})

    def test_the_global_half_is_not_published(self) -> None:
        granted = a_permission('delete_group')
        self.user.user_permissions.add(granted)

        self.assertNotIn(label(granted), resolve_membership_permissions([self.membership])[self.membership.pk])

    def test_the_query_count_does_not_grow_with_the_page(self) -> None:
        group = self.owner_group()
        memberships = [self.membership]

        for index in range(5):
            user = User.objects.create_user(username='member-%s' % index, password='x')
            membership = create_membership(self.organization, user)
            membership.groups.add(group)
            memberships.append(membership)

        # Constant, and nothing per row: the users, the direct grants, the
        # groups, the groups' permissions, and the content types behind them.
        with self.assertNumQueries(5):
            resolved = resolve_membership_permissions(memberships)

        self.assertEqual(len(resolved), 6)

    def test_an_empty_page_asks_nothing(self) -> None:
        with self.assertNumQueries(0):
            self.assertEqual(resolve_membership_permissions([]), {})
