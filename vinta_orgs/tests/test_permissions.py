from typing import TYPE_CHECKING
from unittest import mock

from django.test import RequestFactory
from django.urls import reverse
from model_bakery import baker
from rest_framework.request import Request
from rest_framework.views import APIView

from tests.utils import OrganizationsTestCase
from vinta_orgs.conf import get_organization_model
from vinta_orgs.permissions import DjangoOrganizationModelPermissions, IsOrganizationOwner
from vinta_orgs.tests.factories import (
    clear_current_organization,
    create_organization,
    set_current_organization,
)

# Resolved at runtime, so this module exercises whichever model
# ``ORGANIZATION_MODEL`` names -- the concrete one by default, the test project's
# own under ``tests.settings_swapped``. Type checking always runs against the
# default settings module, so it is shown the concrete model and every lookup
# below keeps the precise type it had.
if TYPE_CHECKING:
    from vinta_orgs.models import Organization
else:
    Organization = get_organization_model()


class DjangoOrganizationModelPermissionsTests(OrganizationsTestCase):
    def setUp(self) -> None:
        super().setUp()
        factory = RequestFactory()
        # Wrapped in DRF's ``Request``, which is what a permission class is
        # actually handed, rather than the bare Django one.
        self.request = Request(factory.post(reverse('vinta_orgs:organization_list')))
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

    def test_has_object_permission_is_denied_from_another_selected_organization(self) -> None:
        # The membership is real and the object belongs to its organization --
        # only the selected organization differs. The check has to narrow to the
        # selection itself now that ``user.memberships`` no longer does.
        other = create_organization(name='other', slug='other')
        set_current_organization(other)
        obj = mock.Mock(spec=['organization'])
        obj.organization = self.organization

        self.assertFalse(self.permission.has_object_permission(self.request, self.view, obj))


class IsOrganizationOwnerTests(OrganizationsTestCase):
    """Owning one organization must not grant ownership of another.

    ``has_permission`` filters on the group alone, so it relied entirely on
    ``user.memberships`` being scoped for the "of *this* organization" half. That
    manager is unscoped now and the narrowing is explicit; this is the test that
    says so.
    """

    def setUp(self) -> None:
        super().setUp()
        factory = RequestFactory()
        self.request = Request(factory.post(reverse('vinta_orgs:organization_list')))
        self.request.user = self.user
        self.view = APIView()
        self.permission = IsOrganizationOwner()

    def test_owner_of_the_selected_organization_is_allowed(self) -> None:
        self.assertTrue(self.permission.has_permission(self.request, self.view))

    def test_owner_of_another_organization_is_denied(self) -> None:
        set_current_organization(create_organization(name='other', slug='other'))

        self.assertFalse(self.permission.has_permission(self.request, self.view))

    def test_nobody_is_an_owner_with_no_organization_selected(self) -> None:
        clear_current_organization()

        self.assertFalse(self.permission.has_permission(self.request, self.view))

    def test_object_permission_is_denied_from_another_selected_organization(self) -> None:
        set_current_organization(create_organization(name='other', slug='other'))
        obj = mock.Mock(spec=['organization'])
        obj.organization = self.organization

        self.assertFalse(self.permission.has_object_permission(self.request, self.view, obj))
