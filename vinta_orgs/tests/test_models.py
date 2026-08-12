#!/usr/bin/env python

"""
test_models
------------

Tests for `django-shared-schema-organizations` models module.
"""

from typing import TYPE_CHECKING

from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.test import TestCase, override_settings

from vinta_orgs.conf import get_organization_membership_model, get_organization_model
from vinta_orgs.exceptions import OrganizationNotFoundError
from vinta_orgs.managers import OrganizationScopedManagerMixin
from vinta_orgs.middleware import OrganizationMiddleware
from vinta_orgs.models import OrganizationSite
from vinta_orgs.state import clear_current_organization, organization_context, set_current_organization

# Resolved at runtime, so this module exercises whichever models
# ``ORGANIZATION_MODEL`` and ``ORGANIZATION_MEMBERSHIP_MODEL`` name -- the
# concrete ones by default, the test project's own under
# ``tests.settings_swapped``. Type checking always runs against the default
# settings module, so it is shown the concrete models and every lookup below
# keeps the precise type it had.
if TYPE_CHECKING:
    from vinta_orgs.models import Organization, OrganizationMembership
else:
    Organization = get_organization_model()
    OrganizationMembership = get_organization_membership_model()


class OrganizationTests(TestCase):
    def test_create(self) -> None:
        organization = Organization(name='test', slug='test')
        organization.save()
        OrganizationMiddleware.set_organization(organization)
        self.assertEqual(Organization.objects.all().count(), 1)
        self.assertEqual(organization.organization_sites.all().count(), 0)


class OrganizationSiteTests(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name='test', slug='test')
        self.site = Site.objects.create(name='test', domain='test.site.com')
        OrganizationMiddleware.set_organization(self.organization)

    def test_create(self) -> None:
        OrganizationSite.objects.create(organization=self.organization, site=self.site)
        self.assertEqual(OrganizationSite.objects.all().count(), 1)


class OrganizationMembershipTests(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name='test', slug='test')
        self.user = User.objects.create_user(
            first_name='test',
            last_name='test',
            username='test',
            email='test@sharedschemaorganizations.com',
            password='test',
        )
        OrganizationMiddleware.set_organization(self.organization)

    def test_create(self) -> None:
        OrganizationMembership.objects.create(organization=self.organization, user=self.user)
        self.assertEqual(OrganizationMembership.objects.all().count(), 1)


class OrganizationMembershipManagerTests(TestCase):
    """Memberships are read across organizations by default.

    A membership says which organizations a user can select; scoping that to the
    organization already selected is circular, and it is inherited by the reverse
    accessors, which is where it did the most damage -- ``user.memberships`` is
    the org-switcher's query and it ran before anything was selected.
    """

    def setUp(self) -> None:
        self.organization_1 = Organization.objects.create(name='organization_1', slug='organization_1')
        self.organization_2 = Organization.objects.create(name='organization_2', slug='organization_2')
        self.user = User.objects.create_user(username='test', password='test')

        # Created with each organization selected in turn, so the rows exist
        # regardless of what the assertions below select.
        for organization in (self.organization_1, self.organization_2):
            with organization_context(organization):
                OrganizationMembership.objects.create(organization=organization, user=self.user)

        clear_current_organization()

    def test_default_manager_is_not_scoped(self) -> None:
        self.assertNotIsInstance(OrganizationMembership._default_manager, OrganizationScopedManagerMixin)

    def test_objects_reads_every_organization(self) -> None:
        self.assertEqual(OrganizationMembership.objects.count(), 2)

    def test_reverse_accessor_on_the_user_reads_every_organization(self) -> None:
        slugs = sorted(membership.organization.slug for membership in self.user.memberships.all())

        self.assertEqual(slugs, ['organization_1', 'organization_2'])

    def test_reverse_accessor_on_the_organization_needs_nothing_selected(self) -> None:
        self.assertEqual(self.organization_1.memberships.count(), 1)

    def test_selecting_an_organization_does_not_narrow_the_default_manager(self) -> None:
        set_current_organization(self.organization_1)

        self.assertEqual(OrganizationMembership.objects.count(), 2)

    def test_scoping_is_still_available_explicitly(self) -> None:
        set_current_organization(self.organization_1)

        self.assertEqual(OrganizationMembership.objects.filter_by_organization(self.organization_2).count(), 1)
        self.assertEqual(self.user.memberships.for_current_organization().count(), 1)
        # Inherited from the mixin and left implicitly scoped, for callers that
        # want the old default.
        self.assertEqual(OrganizationMembership.organization_objects.count(), 1)

    @override_settings(SHARED_SCHEMA_ORGANIZATIONS={'STRICT_ORGANIZATION_FILTER': True})
    def test_strict_filter_leaves_membership_reads_alone(self) -> None:
        # The whole point: under strict filtering these used to raise, and they
        # are exactly the queries that run before an organization is selected.
        self.assertEqual(OrganizationMembership.objects.count(), 2)
        self.assertEqual(self.user.memberships.count(), 2)
        self.assertEqual(self.organization_1.memberships.count(), 1)

    @override_settings(SHARED_SCHEMA_ORGANIZATIONS={'STRICT_ORGANIZATION_FILTER': True})
    def test_strict_filter_still_applies_to_an_explicitly_scoped_read(self) -> None:
        with self.assertRaises(OrganizationNotFoundError):
            OrganizationMembership.organization_objects.count()

        with self.assertRaises(OrganizationNotFoundError):
            self.user.memberships.for_current_organization().count()
