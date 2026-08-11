#!/usr/bin/env python

"""
test_serializers
------------

Tests for `django-shared-schema-organizations` serializers module.
"""

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.urls import reverse
from model_bakery import baker

from organizations.helpers.organizations import set_current_organization
from organizations.models import Organization, OrganizationSite
from organizations.serializers import OrganizationSerializer, OrganizationSiteSerializer


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
        request = factory.post(reverse('organizations:organization_list'))
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
