"""Header and session resolution have to answer to the caller's memberships.

``retrieve_by_domain`` does not: the host is not the caller's to choose. The
other two read something the caller sent, and looking it up without checking
lets any authenticated user select any tenant by typing its slug.
"""

from typing import TYPE_CHECKING, Any, cast

from django.contrib.auth.models import AnonymousUser, User
from django.test import RequestFactory, TestCase, override_settings

from vinta_orgs.conf import get_organization_model
from vinta_orgs.exceptions import (
    AmbiguousOrganizationError,
    OrganizationAccessDeniedError,
    OrganizationNotFoundError,
)
from vinta_orgs.helpers.memberships import create_membership
from vinta_orgs.helpers.organizations import clear_current_organization
from vinta_orgs.organization_retrievers import (
    retrieve_by_http_header,
    retrieve_by_session,
    retrieve_by_user_membership,
)

if TYPE_CHECKING:
    from vinta_orgs.models import Organization
else:
    Organization = get_organization_model()


class HeaderRetrieverTests(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name='acme', slug='acme')
        self.other_organization = Organization.objects.create(name='globex', slug='globex')
        self.user = User.objects.create_user(username='member', password='member')
        self.membership = create_membership(self.organization, self.user)
        clear_current_organization()

    def tearDown(self) -> None:
        clear_current_organization()

    def request(self, slug: str, user: Any = None) -> Any:
        request = RequestFactory().get('/', HTTP_ORGANIZATION_SLUG=slug)

        if user is not None:
            request.user = user

        return request

    def test_a_member_resolves_the_organization_they_named(self) -> None:
        self.assertEqual(retrieve_by_http_header(self.request('acme', self.user)), self.organization)

    def test_a_non_member_is_refused(self) -> None:
        with self.assertRaises(OrganizationAccessDeniedError):
            retrieve_by_http_header(self.request('globex', self.user))

    def test_a_deactivated_member_is_refused(self) -> None:
        self.membership.is_active = False
        self.membership.save()

        with self.assertRaises(OrganizationAccessDeniedError):
            retrieve_by_http_header(self.request('acme', self.user))

    def test_an_anonymous_caller_resolves_as_before(self) -> None:
        # No membership to check and no privilege to escalate: the caller gets
        # whatever that organization exposes publicly, exactly as they would by
        # visiting its domain.
        self.assertEqual(retrieve_by_http_header(self.request('globex', AnonymousUser())), self.other_organization)

    def test_a_request_without_a_user_attribute_resolves_as_before(self) -> None:
        # What ``AuthenticationMiddleware`` not having run yet looks like. The
        # ``vinta_orgs.W001`` system check reports the ordering that causes it.
        self.assertEqual(retrieve_by_http_header(self.request('globex')), self.other_organization)

    def test_a_slug_that_matches_nothing_still_raises_not_found(self) -> None:
        with self.assertRaises(OrganizationNotFoundError):
            retrieve_by_http_header(self.request('nowhere', self.user))

    def test_no_header_resolves_nothing(self) -> None:
        request = RequestFactory().get('/')
        request.user = self.user

        self.assertIsNone(retrieve_by_http_header(request))

    @override_settings(SHARED_SCHEMA_ORGANIZATIONS={'VERIFY_ORGANIZATION_MEMBERSHIP': False})
    def test_the_check_can_be_turned_off(self) -> None:
        self.assertEqual(retrieve_by_http_header(self.request('globex', self.user)), self.other_organization)


class SessionRetrieverTests(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name='acme', slug='acme')
        self.other_organization = Organization.objects.create(name='globex', slug='globex')
        self.user = User.objects.create_user(username='member', password='member')
        create_membership(self.organization, self.user)
        clear_current_organization()

    def request(self, slug: str, user: Any = None) -> Any:
        request = RequestFactory().get('/')
        # A plain dictionary is all the retriever reads of a session, and it
        # keeps the test off ``SessionMiddleware``.
        request.session = cast('Any', {'organization_slug': slug})

        if user is not None:
            request.user = user

        return request

    def test_a_member_resolves_what_the_session_holds(self) -> None:
        self.assertEqual(retrieve_by_session(self.request('acme', self.user)), self.organization)

    def test_a_session_naming_someone_else_is_refused(self) -> None:
        # A session outlives the request that filled it, and any view may write
        # the key.
        with self.assertRaises(OrganizationAccessDeniedError):
            retrieve_by_session(self.request('globex', self.user))

    def test_an_empty_session_resolves_nothing(self) -> None:
        request = RequestFactory().get('/')

        self.assertIsNone(retrieve_by_session(request))


class UserMembershipRetrieverTests(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name='acme', slug='acme')
        self.other_organization = Organization.objects.create(name='globex', slug='globex')
        self.user = User.objects.create_user(username='member', password='member')
        clear_current_organization()

    def request(self, user: Any = None) -> Any:
        request = RequestFactory().get('/')

        if user is not None:
            request.user = user

        return request

    def test_a_caller_with_one_membership_resolves_to_it(self) -> None:
        create_membership(self.organization, self.user)

        self.assertEqual(retrieve_by_user_membership(self.request(self.user)), self.organization)

    def test_a_caller_with_none_resolves_nothing(self) -> None:
        self.assertIsNone(retrieve_by_user_membership(self.request(self.user)))

    def test_a_caller_with_several_is_refused_rather_than_guessed_at(self) -> None:
        create_membership(self.organization, self.user)
        create_membership(self.other_organization, self.user)

        with self.assertRaises(AmbiguousOrganizationError):
            retrieve_by_user_membership(self.request(self.user))

    def test_a_deactivated_membership_does_not_count_towards_ambiguity(self) -> None:
        create_membership(self.organization, self.user)
        deactivated = create_membership(self.other_organization, self.user)
        deactivated.is_active = False
        deactivated.save()

        self.assertEqual(retrieve_by_user_membership(self.request(self.user)), self.organization)

    def test_an_anonymous_caller_resolves_nothing(self) -> None:
        self.assertIsNone(retrieve_by_user_membership(self.request(AnonymousUser())))
