#!/usr/bin/env python

"""
test_serializers
------------

Tests for `django-shared-schema-organizations` serializers module.
"""

from typing import TYPE_CHECKING

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.urls import reverse
from model_bakery import baker

from vinta_orgs.conf import get_organization_model
from vinta_orgs.models import OrganizationSite
from vinta_orgs.serializers import OrganizationSerializer, OrganizationSiteSerializer
from vinta_orgs.tests.factories import set_current_organization

# Resolved at runtime, so this module exercises whichever model
# ``ORGANIZATION_MODEL`` names -- the concrete one by default, the test project's
# own under ``tests.settings_swapped``. Type checking always runs against the
# default settings module, so it is shown the concrete model and every lookup
# below keeps the precise type it had.
if TYPE_CHECKING:
    from vinta_orgs.models import Organization
else:
    Organization = get_organization_model()


class OrganizationSerializerTests(TestCase):
    def setUp(self) -> None:
        self.organizations = baker.make(Organization, _quantity=10)
        self.user = User.objects.create_user(
            first_name='test',
            last_name='test',
            username='test',
            email='test@sharedschemaorganizations.com',
            password='test',
        )
        set_current_organization(self.organizations[0].slug)
        self.params = {
            'name': 'test 2',
            'slug': 'test-2',
        }

    def test_serialize(self) -> None:
        data = OrganizationSerializer(Organization.objects.all().first()).data
        keys = ['name', 'slug']
        try:
            self.assertCountEqual(data.keys(), keys)
        except AttributeError:
            self.assertEqual(len(data.keys()), len(keys))
            for key in keys:
                self.assertTrue(key in data.keys())

    def test_create(self) -> None:
        factory = RequestFactory()
        request = factory.post(reverse('vinta_orgs:organization_list'))
        request.user = self.user
        serializer = OrganizationSerializer(data=self.params, context={'request': request})
        self.assertTrue(serializer.is_valid())
        organization = serializer.save()

        self.assertEqual(organization.name, self.params['name'])
        self.assertEqual(organization.slug, self.params['slug'])

    def test_update(self) -> None:
        organization = self.organizations[0]
        serializer = OrganizationSerializer(organization, data=self.params)

        self.assertTrue(serializer.is_valid())
        serializer.save()

        organization = Organization.objects.get(slug=self.params['slug'])

        self.assertEqual(organization.name, self.params['name'])
        self.assertEqual(organization.slug, self.params['slug'])

    def test_partial_update(self) -> None:
        organization = self.organizations[0]
        serializer = OrganizationSerializer(organization, data={'name': 'test 3'}, partial=True)

        self.assertTrue(serializer.is_valid())
        serializer.save()

        organization.refresh_from_db()

        self.assertEqual(organization.name, 'test 3')


class OrganizationSiteSerializerTests(TestCase):
    def setUp(self) -> None:
        self.organization = baker.make(Organization)
        self.user = User.objects.create_user(
            first_name='test',
            last_name='test',
            username='test',
            email='test@sharedschemaorganizations.com',
            password='test',
        )
        self.organization_site = baker.make(OrganizationSite, organization=self.organization)

        self.params = {'domain': 'sharedschemaorganizations.com'}
        set_current_organization(self.organization.slug)

    def test_serialize(self) -> None:
        data = OrganizationSiteSerializer(self.organization_site).data
        keys = ['id', 'domain']
        try:
            self.assertCountEqual(data.keys(), keys)
        except AttributeError:
            self.assertEqual(len(data.keys()), len(keys))
            for key in keys:
                self.assertTrue(key in data.keys())

    def test_create(self) -> None:
        serializer = OrganizationSiteSerializer(data=self.params)
        self.assertTrue(serializer.is_valid())
        organization_site = serializer.save()
        self.assertEqual(organization_site.site.domain, self.params['domain'])
