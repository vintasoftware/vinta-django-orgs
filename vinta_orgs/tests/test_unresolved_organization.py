from django.contrib.auth.models import AnonymousUser, User
from django.test import TestCase

from vinta_orgs.exceptions import OrganizationAccessDeniedError
from vinta_orgs.tests.factories import (
    UNRESOLVED_ORGANIZATION,
    create_membership,
    create_organization,
    resolve_membership_for_user,
)


class UnresolvedOrganizationTests(TestCase):
    def setUp(self) -> None:
        self.organization = create_organization(name='organization', slug='organization')
        self.user = User.objects.create_user(username='member')
        create_membership(self.organization, self.user)

    def test_public_sentinel_refuses_a_nonexistent_non_slug_identifier(self) -> None:
        with self.assertRaises(OrganizationAccessDeniedError):
            resolve_membership_for_user(self.user, UNRESOLVED_ORGANIZATION)

    def test_optional_resolution_turns_the_sentinel_into_none(self) -> None:
        self.assertIsNone(resolve_membership_for_user(self.user, UNRESOLVED_ORGANIZATION, strict=False))

    def test_anonymous_resolution_remains_none(self) -> None:
        self.assertIsNone(resolve_membership_for_user(AnonymousUser(), UNRESOLVED_ORGANIZATION))
