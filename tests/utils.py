from typing import TYPE_CHECKING

from django.contrib.auth.models import User
from django.test import TestCase
from model_bakery import baker
from rest_framework.test import APITestCase

from vinta_orgs.conf import get_organization_model
from vinta_orgs.helpers.memberships import create_membership
from vinta_orgs.helpers.organizations import create_default_organization_groups, set_current_organization
from vinta_orgs.models import OrganizationSite

# Resolved at runtime, so this module exercises whichever model
# ``ORGANIZATION_MODEL`` names -- the concrete one by default, the test project's
# own under ``tests.settings_swapped``. Type checking always runs against the
# default settings module, so it is shown the concrete model and every lookup
# below keeps the precise type it had.
if TYPE_CHECKING:
    from vinta_orgs.models import Organization
else:
    Organization = get_organization_model()


class OrganizationsTestCase(TestCase):
    def setUp(self) -> None:
        self.organization = baker.make(Organization)
        set_current_organization(self.organization.slug)
        self.user = User.objects.create_user(
            first_name='test',
            last_name='test',
            username='test',
            email='test@sharedschemaorganizations.com',
            password='test',
        )
        self.membership = create_membership(self.organization, self.user, groups=create_default_organization_groups())
        self.organization_site = baker.make(OrganizationSite, organization=self.organization)


class OrganizationsAPITestCase(APITestCase):
    def setUp(self) -> None:
        self.organization = baker.make(Organization)
        set_current_organization(self.organization.slug)
        self.user = User.objects.create_user(
            first_name='test',
            last_name='test',
            username='test',
            email='test@sharedschemaorganizations.com',
            password='test',
        )
        self.membership = create_membership(self.organization, self.user, groups=create_default_organization_groups())
        self.organization_site = baker.make(OrganizationSite, organization=self.organization)
