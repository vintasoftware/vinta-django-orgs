from typing import TYPE_CHECKING

#!/usr/bin/env python
from django.contrib.auth.models import User
from django.urls import reverse
from model_bakery import baker
from rest_framework import status
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


class OrganizationListViewTests(APITestCase):
    def setUp(self) -> None:
        self.organizations = baker.make(Organization, _quantity=10)
        set_current_organization(self.organizations[0].slug)
        self.user = User.objects.create_user(
            first_name='test',
            last_name='test',
            username='test',
            email='test@sharedschemaorganizations.com',
            password='test',
        )
        groups = create_default_organization_groups()
        create_membership(self.organizations[0], self.user, groups)
        self.params = {
            'name': 'test 2',
            'slug': 'test-2',
        }
        self.view_url = reverse('vinta_orgs:organization_list')
        self.client.force_authenticate(self.user)

    def test_list(self) -> None:
        response = self.client.get(self.view_url, HTTP_ORGANIZATION_SLUG=self.organizations[0].slug)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create(self) -> None:
        response = self.client.post(self.view_url, self.params, HTTP_ORGANIZATION_SLUG=self.organizations[0].slug)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class OrganizationDetailsViewTests(APITestCase):
    def setUp(self) -> None:
        self.organizations = baker.make(Organization, _quantity=10)
        set_current_organization(self.organizations[0].slug)
        self.user = User.objects.create_user(
            first_name='test',
            last_name='test',
            username='test',
            email='test@sharedschemaorganizations.com',
            password='test',
        )
        groups = create_default_organization_groups()
        create_membership(self.organizations[0], self.user, groups)
        self.params = {
            'name': 'test 2',
            'slug': 'test-2',
        }
        self.view_url = reverse('vinta_orgs:organization_details')
        self.client.force_authenticate(self.user)

    def test_update(self) -> None:
        response = self.client.put(self.view_url, self.params, HTTP_ORGANIZATION_SLUG=self.organizations[0].slug)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        organization = Organization.objects.get(slug=response.data['slug'])
        self.assertEqual(organization.name, self.params['name'])
        self.assertEqual(organization.slug, self.params['slug'])

    def test_partial_update(self) -> None:
        response = self.client.patch(
            self.view_url,
            {'name': 'test 3'},
            HTTP_ORGANIZATION_SLUG=self.organizations[0].slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        organization = Organization.objects.get(slug=self.organizations[0].slug)
        self.assertEqual(organization.name, 'test 3')


class OrganizationSiteListViewTests(APITestCase):
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
        groups = create_default_organization_groups()
        create_membership(self.organization, self.user, groups)

        self.organization_site = baker.make(OrganizationSite, organization=self.organization)

        self.params = {'domain': 'sharedschemaorganizations.com'}
        self.view_url = reverse('vinta_orgs:organization_site_list')
        self.client.force_authenticate(self.user)

    def test_list(self) -> None:
        response = self.client.get(self.view_url, HTTP_ORGANIZATION_SLUG=self.organization.slug)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(len(response.data), 1)
        self.assertTrue(response.data[0].get('id'), self.organization_site.id)

    def test_create(self) -> None:
        response = self.client.post(self.view_url, self.params, HTTP_ORGANIZATION_SLUG=self.organization.slug)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['domain'], self.params['domain'])

        set_current_organization(self.organization.slug)
        organization_site = OrganizationSite.objects.filter(id=response.data['id']).first()
        self.assertIsNotNone(organization_site)


class OrganizationSiteDetailsViewTests(APITestCase):
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
        groups = create_default_organization_groups()
        create_membership(self.organization, self.user, groups)

        self.organization_site = baker.make(OrganizationSite, organization=self.organization)

        self.params = {'domain': 'sharedschemaorganizations.com'}
        self.view_url = reverse('vinta_orgs:organization_site_details', kwargs={'pk': self.organization_site.pk})
        self.client.force_authenticate(self.user)

    def test_delete(self) -> None:
        response = self.client.delete(self.view_url, HTTP_ORGANIZATION_SLUG=self.organization.slug)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        organization_site = OrganizationSite.objects.filter(pk=self.organization_site.pk).first()
        self.assertIsNone(organization_site)
