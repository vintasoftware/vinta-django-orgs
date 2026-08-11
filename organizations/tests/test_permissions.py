from unittest import mock

from django.test import RequestFactory
from django.urls import reverse
from model_bakery import baker
from rest_framework.request import Request
from rest_framework.views import APIView

from organizations.models import Organization
from organizations.permissions import DjangoOrganizationModelPermissions
from tests.utils import OrganizationsTestCase


class DjangoOrganizationModelPermissionsTests(OrganizationsTestCase):
    def setUp(self) -> None:
        super().setUp()
        factory = RequestFactory()
        # Wrapped in DRF's ``Request``, which is what a permission class is
        # actually handed, rather than the bare Django one.
        self.request = Request(factory.post(reverse('organizations:organization_list')))
        self.request.user = self.user
        self.view = APIView()
        self.permission = DjangoOrganizationModelPermissions()

    def test_has_object_permission_with_created_organization_single_organization_object(self) -> None:
        obj = mock.Mock(spec=['organization'])
        obj.organization = self.organization
        self.assertTrue(self.permission.has_object_permission(self.request, self.view, obj))

    def test_has_object_permission_with_created_organization_multi_organization_object(self) -> None:
        obj = mock.Mock(spec=['organizations'])
        obj.organizations = mock.Mock(spec=['all'])
        obj.organizations.all = lambda: [self.organization]
        self.assertTrue(self.permission.has_object_permission(self.request, self.view, obj))

    def test_has_object_permission_with_new_organization_single_organization_object(self) -> None:
        obj = mock.Mock(spec=['organization'])
        obj.organization = baker.make(Organization)
        self.assertFalse(self.permission.has_object_permission(self.request, self.view, obj))

    def test_has_object_permission_with_new_organization_multi_organization_object(self) -> None:
        obj = mock.Mock(spec=['organizations'])
        obj.organizations = mock.Mock(spec=['all'])
        obj.organizations.all = lambda: [baker.make(Organization)]
        self.assertFalse(self.permission.has_object_permission(self.request, self.view, obj))

    def test_has_object_permission_without_organization_attributes(self) -> None:
        obj = mock.Mock(spec=['test_not_organization_attribute'])
        self.assertTrue(self.permission.has_object_permission(self.request, self.view, obj))
