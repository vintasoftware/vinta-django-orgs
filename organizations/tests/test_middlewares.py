from typing import Any
from unittest import mock

from django.contrib.sessions.middleware import SessionMiddleware
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from organizations.exceptions import OrganizationNotFoundError
from organizations.helpers.organizations import (
    clear_current_organization,
    create_organization,
    get_current_organization,
    set_current_organization,
)
from organizations.middleware import OrganizationMiddleware, OrganizationRequest, get_organization
from organizations.models import Organization


class OrganizationMiddlewareTests(TestCase):
    @mock.patch('organizations.middleware.OrganizationMiddleware.process_request')
    @mock.patch('organizations.middleware.OrganizationMiddleware.process_response')
    def test_calls_process_request_and_process_response(
        self, process_request: mock.MagicMock, process_response: mock.MagicMock
    ) -> None:
        factory = RequestFactory()
        request = factory.get(reverse('organizations:organization_list'), HTTP_HOST='test.localhost:8000')

        response = HttpResponse()
        OrganizationMiddleware(lambda r: response).__call__(request)
        process_request.assert_called_once()
        process_response.assert_called_once()

    @mock.patch('organizations.middleware.get_organization')
    def test_process_request_adds_organization_to_request(self, get_organization: mock.MagicMock) -> None:
        organization = create_organization(name='test', slug='test', domains=['test.localhost:8000'])
        get_organization.return_value = organization
        factory = RequestFactory()
        request = factory.get(reverse('organizations:organization_list'), HTTP_HOST='test.localhost:8000')
        response = HttpResponse()
        processed = OrganizationMiddleware(lambda r: response).process_request(request)

        assert processed.organization is not None
        self.assertEqual(processed.organization.slug, organization.slug)
        get_organization.assert_called_once()

    def test_call_returns_correct_response(self) -> None:
        create_organization(name='test', slug='test', domains=['test.localhost:8000'])
        factory = RequestFactory()
        request = factory.get(reverse('organizations:organization_list'), HTTP_HOST='test.localhost:8000')

        response = HttpResponse()
        processed_response = OrganizationMiddleware(lambda r: response).__call__(request)

        self.assertEqual(response, processed_response)


class GetOrganizationTests(TestCase):
    def test_with_correct_domain(self) -> None:
        organization = create_organization(name='test', slug='test', domains=['test.localhost:8000'])
        factory = RequestFactory()
        request = factory.get(reverse('organizations:organization_list'), HTTP_HOST='test.localhost:8000')
        retrieved_organization = get_organization(request)

        self.assertEqual(retrieved_organization, organization)

    def test_with_http_header(self) -> None:
        organization = create_organization(name='test', slug='test', domains=['test.localhost:8000'])
        factory = RequestFactory()
        request = factory.get(reverse('organizations:organization_list'), HTTP_ORGANIZATION_SLUG=organization.slug)

        retrieved_organization = get_organization(request)

        self.assertEqual(retrieved_organization, organization)

    def test_with_unexistent_organization_in_http_header(self) -> None:
        create_organization(name='test', slug='test', domains=['test.localhost:8000'])
        factory = RequestFactory()
        request = factory.get(reverse('organizations:organization_list'), HTTP_ORGANIZATION_SLUG='unexistent')

        with self.assertRaises(OrganizationNotFoundError):
            get_organization(request)

    def test_with_previously_set_organization(self) -> None:
        organization = create_organization(name='test', slug='test', domains=['test.localhost:8000'])
        factory = RequestFactory()
        request = factory.get(reverse('organizations:organization_list'))

        set_current_organization(organization.slug)
        retrieved_organization = get_organization(request)

        self.assertEqual(retrieved_organization, organization)

    def test_with_nothing(self) -> None:
        factory = RequestFactory()
        request = factory.get(reverse('organizations:organization_list'))

        retrieved_organization = get_organization(request)

        self.assertEqual(retrieved_organization, None)


class OrganizationBindingTests(TestCase):
    """The middleware binds the organization for the request and only for it."""

    def setUp(self) -> None:
        self.organization = create_organization(name='test', slug='test', domains=['test.localhost:8000'])
        self.factory = RequestFactory()
        clear_current_organization()

    def tearDown(self) -> None:
        clear_current_organization()

    def _request(self, **extra: Any) -> WSGIRequest:
        return self.factory.get(reverse('organizations:organization_list'), **extra)

    def test_organization_is_bound_while_the_view_runs(self) -> None:
        seen: list[Organization | None] = []

        def get_response(request: HttpRequest) -> HttpResponse:
            seen.append(get_current_organization())
            return HttpResponse()

        OrganizationMiddleware(get_response)(self._request(HTTP_HOST='test.localhost:8000'))

        self.assertEqual(seen, [self.organization])

    def test_binding_is_released_after_the_response(self) -> None:
        OrganizationMiddleware(lambda r: HttpResponse())(self._request(HTTP_HOST='test.localhost:8000'))

        self.assertIsNone(get_current_organization())

    def test_previous_binding_is_restored_after_the_response(self) -> None:
        other_organization = create_organization(name='other', slug='other')
        set_current_organization(other_organization)

        OrganizationMiddleware(lambda r: HttpResponse())(self._request(HTTP_HOST='test.localhost:8000'))

        self.assertEqual(get_current_organization(), other_organization)

    def test_binding_is_released_when_the_view_raises(self) -> None:
        def get_response(request: HttpRequest) -> HttpResponse:
            raise ValueError()

        with self.assertRaises(ValueError):
            OrganizationMiddleware(get_response)(self._request(HTTP_HOST='test.localhost:8000'))

        self.assertIsNone(get_current_organization())

    def test_request_nothing_identifies_resolves_to_nothing(self) -> None:
        request = OrganizationMiddleware(lambda r: HttpResponse()).process_request(self._request())

        # Reading the binding the middleware itself installed used to recurse
        # until the stack ran out.
        self.assertFalse(request.organization)

    def test_organization_is_resolved_once_per_request(self) -> None:
        request = OrganizationMiddleware(lambda r: HttpResponse()).process_request(
            self._request(HTTP_HOST='test.localhost:8000')
        )

        with self.assertNumQueries(1):
            self.assertEqual(request.organization, self.organization)
            self.assertEqual(request.organization, self.organization)


class SessionWriteTests(TestCase):
    """The session is only written when the organization actually changes.

    Assigning a session key marks the session modified, and ``SessionMiddleware``
    then saves it -- a database write on every request for the default backend,
    to store a slug that was already there.
    """

    def setUp(self) -> None:
        self.organization = create_organization(name='test', slug='test', domains=['test.localhost:8000'])
        clear_current_organization()

    def _request(self, session_slug: str | None = None) -> OrganizationRequest:
        request = RequestFactory().get('/', HTTP_HOST='test.localhost:8000')
        SessionMiddleware(lambda r: HttpResponse()).process_request(request)

        if session_slug is not None:
            request.session['organization_slug'] = session_slug
            request.session.modified = False

        return OrganizationMiddleware(lambda r: HttpResponse()).process_request(request)

    def test_session_is_not_rewritten_when_the_organization_is_unchanged(self) -> None:
        request = self._request(session_slug='test')

        assert request.organization is not None
        self.assertEqual(request.organization.slug, 'test')
        self.assertFalse(request.session.modified)

    def test_session_is_written_when_it_holds_another_organization(self) -> None:
        request = self._request(session_slug='somewhere-else')

        assert request.organization is not None
        self.assertEqual(request.organization.slug, 'test')
        self.assertTrue(request.session.modified)
        self.assertEqual(request.session['organization_slug'], 'test')

    def test_session_is_written_when_it_holds_nothing(self) -> None:
        request = self._request()

        assert request.organization is not None
        self.assertEqual(request.organization.slug, 'test')
        self.assertTrue(request.session.modified)
        self.assertEqual(request.session['organization_slug'], 'test')
