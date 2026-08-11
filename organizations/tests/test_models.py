#!/usr/bin/env python

"""
test_models
------------

Tests for `django-shared-schema-organizations` models module.
"""

from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.test import TestCase

from organizations.middleware import OrganizationMiddleware
from organizations.models import Organization, OrganizationMembership, OrganizationSite


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
