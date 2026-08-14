"""The project-level typed service wrappers."""

from typing import TYPE_CHECKING

from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase

from vinta_orgs.conf import get_organization_membership_model, get_organization_model
from vinta_orgs.models import OrganizationSite
from vinta_orgs.services import MembershipService, OrganizationService
from vinta_orgs.state import clear_current_organization, set_current_organization

if TYPE_CHECKING:
    from vinta_orgs.models import Organization, OrganizationMembership
else:
    Organization = get_organization_model()
    OrganizationMembership = get_organization_membership_model()


class OrganizationServiceTests(TestCase):
    def setUp(self) -> None:
        self.service = OrganizationService(Organization)
        clear_current_organization()

    def tearDown(self) -> None:
        clear_current_organization()

    def test_exposes_the_validated_model(self) -> None:
        self.assertIs(self.service.model, Organization)

    def test_create_update_and_current_preserve_the_concrete_model(self) -> None:
        organization = self.service.create('Acme', 'acme')
        updated = self.service.update(organization, name='Acme Inc.')
        set_current_organization(updated)

        self.assertIs(type(organization), Organization)
        self.assertIs(updated, organization)
        self.assertEqual(updated.name, 'Acme Inc.')
        self.assertIs(self.service.get_current(), organization)

    def test_rejects_a_model_that_is_not_configured(self) -> None:
        with self.assertRaises(ImproperlyConfigured):
            OrganizationService(OrganizationSite)  # type: ignore[type-var]


class MembershipServiceTests(TestCase):
    def setUp(self) -> None:
        self.organizations = OrganizationService(Organization)
        self.memberships = MembershipService(self.organizations, OrganizationMembership)
        self.organization = self.organizations.create('Acme', 'acme')
        self.user = User.objects.create_user(username='member')

    def test_exposes_the_validated_model(self) -> None:
        self.assertIs(self.memberships.model, OrganizationMembership)

    def test_create_active_and_resolve_preserve_the_concrete_models(self) -> None:
        membership = self.memberships.create(self.organization, self.user)

        self.assertIs(type(membership), OrganizationMembership)
        self.assertEqual(list(self.memberships.get_active(self.user)), [membership])
        self.assertEqual(self.memberships.resolve_for_user(self.user), membership)
        self.assertEqual(self.organizations.resolve_for_user(self.user), self.organization)

    def test_rejects_a_membership_model_that_is_not_configured(self) -> None:
        with self.assertRaises(ImproperlyConfigured):
            MembershipService(self.organizations, OrganizationSite)  # type: ignore[type-var]
