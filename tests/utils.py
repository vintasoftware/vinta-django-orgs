from django.contrib.auth.models import User
from django.test import TestCase
from model_bakery import baker
from rest_framework.test import APITestCase

from organizations.helpers.memberships import create_membership
from organizations.helpers.organizations import create_default_organization_groups, set_current_organization
from organizations.models import Organization, OrganizationSite


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
