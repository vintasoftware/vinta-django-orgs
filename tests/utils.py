from typing import TYPE_CHECKING

from django.contrib.auth.models import User
from django.test import TestCase
from model_bakery import baker
from rest_framework.test import APITestCase

from vinta_orgs.conf import get_organization_membership_model, get_organization_model
from vinta_orgs.models import OrganizationSite
from vinta_orgs.services import MembershipService, OrganizationService
from vinta_orgs.state import organization_state

# Resolved at runtime, so this module exercises whichever model
# ``ORGANIZATION_MODEL`` names -- the concrete one by default, the test project's
# own under ``tests.settings_swapped``. Type checking always runs against the
# default settings module, so it is shown the concrete model and every lookup
# below keeps the precise type it had.
if TYPE_CHECKING:
    from vinta_orgs.models import Organization, OrganizationMembership
else:
    Organization = get_organization_model()
    OrganizationMembership = get_organization_membership_model()

organizations: OrganizationService[Organization] = OrganizationService()
memberships: MembershipService[Organization, OrganizationMembership] = MembershipService()


class OrganizationsTestCase(TestCase):
    def setUp(self) -> None:
        self.organization = baker.make(Organization)
        organization_state.set(self.organization.slug)
        self.user = User.objects.create_user(
            first_name='test',
            last_name='test',
            username='test',
            email='test@sharedschemaorganizations.com',
            password='test',
        )
        self.membership = memberships.create(
            self.organization,
            self.user,
            groups=organizations.create_default_groups(),
        )
        self.organization_site = baker.make(OrganizationSite, organization=self.organization)


class OrganizationsAPITestCase(APITestCase):
    def setUp(self) -> None:
        self.organization = baker.make(Organization)
        organization_state.set(self.organization.slug)
        self.user = User.objects.create_user(
            first_name='test',
            last_name='test',
            username='test',
            email='test@sharedschemaorganizations.com',
            password='test',
        )
        self.membership = memberships.create(
            self.organization,
            self.user,
            groups=organizations.create_default_groups(),
        )
        self.organization_site = baker.make(OrganizationSite, organization=self.organization)
