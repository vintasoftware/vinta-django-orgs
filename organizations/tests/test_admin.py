"""The admin changelists must not cost a query per row.

``OrganizationMembership.__str__`` reads the user, the organization and every
group, and the changelist renders it once per row.
"""

from django.contrib import admin
from django.contrib.auth.models import User
from django.test import RequestFactory

from organizations.helpers.memberships import create_membership
from organizations.helpers.organizations import create_default_organization_groups
from organizations.models import OrganizationMembership, OrganizationSite
from tests.utils import OrganizationsTestCase


class AdminQueryCountTests(OrganizationsTestCase):
    def setUp(self) -> None:
        super().setUp()
        groups = create_default_organization_groups()

        for index in range(4):
            member = User.objects.create_user(username='member-%d' % index, password='test')
            create_membership(self.organization, member, groups=groups)

        self.request = RequestFactory().get('/')
        self.request.user = self.user

    def test_membership_changelist_does_not_query_per_row(self) -> None:
        model_admin = admin.site._registry[OrganizationMembership]
        queryset = model_admin.get_queryset(self.request)

        # One for the rows, with the user and organization joined in, and one
        # for every row's groups together.
        with self.assertNumQueries(2):
            labels = [str(membership) for membership in queryset]

        self.assertEqual(len(labels), 5)

    def test_organization_site_inline_does_not_query_per_row(self) -> None:
        model_admin = admin.site._registry[type(self.organization)]
        inline = model_admin.inlines[0](type(self.organization), admin.site)

        # Built outside the assertion: an inline checks permissions before it
        # hands back a queryset, which is a one-off cost and not what is being
        # measured here.
        queryset = inline.get_queryset(self.request)

        with self.assertNumQueries(1):
            labels = [str(organization_site) for organization_site in queryset]

        self.assertEqual(labels, [str(OrganizationSite.objects.first())])
