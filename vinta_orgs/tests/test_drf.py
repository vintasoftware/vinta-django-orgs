"""The DRF seam: resolution after authentication, binding released on every path.

The middleware cannot do this. It runs before DRF authentication, so on a
project using token or JWT authentication ``request.user`` is anonymous at the
point the middleware resolves -- there is no user to check a header against, and
no membership to fall back on.
"""

from typing import TYPE_CHECKING, Any

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from vinta_orgs.conf import get_organization_model
from vinta_orgs.drf import OrganizationScopedAPIViewMixin
from vinta_orgs.tests.factories import (
    clear_current_organization,
    create_membership,
    get_current_organization,
    set_current_organization,
)

if TYPE_CHECKING:
    from vinta_orgs.models import Organization
else:
    Organization = get_organization_model()


class HeaderAuthentication(BaseAuthentication):
    """Authentication that only DRF can do, which is the point.

    Reads a header rather than a session, so ``request.user`` is anonymous for
    the whole of the Django middleware chain and only becomes real inside
    ``APIView.initial``.
    """

    def authenticate(self, request: Any) -> tuple[User, None] | None:
        username = request.META.get('HTTP_X_TEST_USER')

        if not username:
            return None

        return User.objects.get(username=username), None


class RecordingView(OrganizationScopedAPIViewMixin, APIView):
    authentication_classes = [HeaderAuthentication]
    permission_classes: list[Any] = []

    def get(self, request: Any) -> Response:
        organization = get_current_organization()

        return Response(
            {
                'bound': organization.slug if organization else None,
                'request': request.organization.slug if request.organization else None,
                'membership': request.organization_membership.pk if request.organization_membership else None,
            }
        )


class OrganizationBoundAtPermissionTime(BasePermission):
    """Records what was bound when the permission stack ran."""

    seen: list[str | None] = []

    def has_permission(self, request: Any, view: Any) -> bool:
        organization = get_current_organization()
        type(self).seen.append(organization.slug if organization else None)
        return True


class PermissionOrderView(RecordingView):
    permission_classes = [OrganizationBoundAtPermissionTime]


class OptionalView(RecordingView):
    organization_resolution_optional = True


class RaisingView(RecordingView):
    def get(self, request: Any) -> Response:
        raise RuntimeError('boom')


class DRFResolutionTestCase(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name='acme', slug='acme')
        self.other_organization = Organization.objects.create(name='globex', slug='globex')
        self.user = User.objects.create_user(username='member', password='member')
        self.membership = create_membership(self.organization, self.user)
        self.factory = APIRequestFactory()
        clear_current_organization()

    def tearDown(self) -> None:
        clear_current_organization()

    def call(self, view: Any, *, user: User | None = None, slug: str | None = None) -> Any:
        headers: dict[str, Any] = {}

        if user is not None:
            headers['HTTP_X_TEST_USER'] = user.username

        if slug is not None:
            headers['HTTP_ORGANIZATION_SLUG'] = slug

        return view.as_view()(self.factory.get('/', **headers))


class ResolutionTests(DRFResolutionTestCase):
    def test_a_single_membership_resolves_without_a_header(self) -> None:
        response = self.call(RecordingView, user=self.user)

        self.assertEqual(response.data['bound'], 'acme')
        self.assertEqual(response.data['request'], 'acme')
        self.assertEqual(response.data['membership'], self.membership.pk)

    def test_a_header_naming_a_membership_resolves_to_it(self) -> None:
        create_membership(self.other_organization, self.user)

        response = self.call(RecordingView, user=self.user, slug='globex')

        self.assertEqual(response.data['bound'], 'globex')

    def test_several_memberships_and_no_header_is_a_400(self) -> None:
        create_membership(self.other_organization, self.user)

        response = self.call(RecordingView, user=self.user)

        self.assertEqual(response.status_code, 400)

    def test_a_header_naming_a_non_membership_is_a_403(self) -> None:
        response = self.call(RecordingView, user=self.user, slug='globex')

        self.assertEqual(response.status_code, 403)

    def test_an_anonymous_caller_resolves_nothing_rather_than_being_refused(self) -> None:
        # 401/403 is the permission stack's answer to give, and it runs after
        # this. A resolver that raised first would answer the wrong status.
        response = self.call(RecordingView)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['bound'])

    def test_a_deactivated_membership_does_not_resolve(self) -> None:
        self.membership.is_active = False
        self.membership.save()

        response = self.call(RecordingView, user=self.user)

        self.assertIsNone(response.data['bound'])


class OptOutTests(DRFResolutionTestCase):
    def test_an_opted_out_view_gates_instead_of_refusing_an_ambiguous_caller(self) -> None:
        create_membership(self.other_organization, self.user)

        response = self.call(OptionalView, user=self.user)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['bound'])

    def test_an_opted_out_view_gates_instead_of_refusing_a_non_member(self) -> None:
        response = self.call(OptionalView, user=self.user, slug='globex')

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['bound'])

    def test_a_named_action_opts_out_on_its_own(self) -> None:
        class ActionView(RecordingView):
            organization_optional_actions = ('mine',)
            action = 'mine'

        create_membership(self.other_organization, self.user)

        self.assertEqual(self.call(ActionView, user=self.user).status_code, 200)

    def test_a_different_action_keeps_the_refusal(self) -> None:
        class ActionView(RecordingView):
            organization_optional_actions = ('mine',)
            action = 'list'

        create_membership(self.other_organization, self.user)

        self.assertEqual(self.call(ActionView, user=self.user).status_code, 400)


class OrderingTests(DRFResolutionTestCase):
    def test_the_organization_is_bound_before_the_permission_stack_runs(self) -> None:
        # The bug this seam exists to prevent: permission classes answering for
        # one organization while ``get_queryset`` serves another.
        OrganizationBoundAtPermissionTime.seen = []
        create_membership(self.other_organization, self.user)

        self.call(PermissionOrderView, user=self.user, slug='globex')

        self.assertEqual(OrganizationBoundAtPermissionTime.seen, ['globex'])


class BindingLifecycleTests(DRFResolutionTestCase):
    def test_the_binding_is_released_after_the_response(self) -> None:
        self.call(RecordingView, user=self.user)

        self.assertIsNone(get_current_organization())

    def test_the_previous_binding_is_restored_rather_than_cleared(self) -> None:
        set_current_organization(self.other_organization)

        self.call(RecordingView, user=self.user)

        self.assertEqual(get_current_organization(), self.other_organization)

    def test_the_binding_is_released_when_the_view_raises_past_drf(self) -> None:
        # ``RuntimeError`` is not an ``APIException``, so ``handle_exception``
        # re-raises it and ``finalize_response`` never runs. A binding left
        # behind here would be read by the next request this worker serves.
        with self.assertRaises(RuntimeError):
            self.call(RaisingView, user=self.user)

        self.assertIsNone(get_current_organization())

    def test_the_binding_is_released_after_a_refusal(self) -> None:
        set_current_organization(self.other_organization)

        self.call(RecordingView, user=self.user, slug='globex')

        self.assertEqual(get_current_organization(), self.other_organization)

    def test_re_binding_mid_request_does_not_leak_a_frame(self) -> None:
        set_current_organization(self.other_organization)
        view = RecordingView()

        view.bind_organization(self.organization)
        view.bind_organization(self.organization)
        view.unbind_organization()

        self.assertEqual(get_current_organization(), self.other_organization)
