"""The startup check for the middleware ordering that disables a security control."""

from django.test import SimpleTestCase, override_settings

from vinta_orgs.checks import (
    AUTHENTICATION_MIDDLEWARE,
    ORGANIZATION_MIDDLEWARE,
    check_middleware_order,
)

SAFE_ORDER = [
    'django.contrib.sessions.middleware.SessionMiddleware',
    AUTHENTICATION_MIDDLEWARE,
    ORGANIZATION_MIDDLEWARE,
]
UNSAFE_ORDER = [ORGANIZATION_MIDDLEWARE, AUTHENTICATION_MIDDLEWARE]

DOMAIN_ONLY = {'ORGANIZATION_RETRIEVERS': ['vinta_orgs.organization_retrievers.retrieve_by_domain']}


class MiddlewareOrderCheckTests(SimpleTestCase):
    def ids(self, **settings_kwargs: object) -> list[str | None]:
        with override_settings(**settings_kwargs):
            return [warning.id for warning in check_middleware_order()]

    @override_settings(MIDDLEWARE=UNSAFE_ORDER)
    def test_the_unsafe_order_is_reported(self) -> None:
        self.assertEqual([warning.id for warning in check_middleware_order()], ['vinta_orgs.W001'])

    @override_settings(MIDDLEWARE=SAFE_ORDER)
    def test_the_safe_order_is_not(self) -> None:
        self.assertEqual(check_middleware_order(), [])

    def test_a_project_without_the_organization_middleware_is_not_reported(self) -> None:
        self.assertEqual(self.ids(MIDDLEWARE=[AUTHENTICATION_MIDDLEWARE]), [])

    def test_a_project_without_the_authentication_middleware_is_not_reported(self) -> None:
        # Nothing to order against, and no ``request.user`` on any request --
        # which the retriever handles by resolving as it always did.
        self.assertEqual(self.ids(MIDDLEWARE=[ORGANIZATION_MIDDLEWARE]), [])

    def test_turning_the_verification_off_silences_it(self) -> None:
        self.assertEqual(
            self.ids(
                MIDDLEWARE=UNSAFE_ORDER,
                SHARED_SCHEMA_ORGANIZATIONS={'VERIFY_ORGANIZATION_MEMBERSHIP': False},
            ),
            [],
        )

    def test_resolving_by_domain_alone_silences_it(self) -> None:
        # The host is not the caller's to choose, so there is nothing to check
        # against the caller and the ordering does not matter.
        self.assertEqual(self.ids(MIDDLEWARE=UNSAFE_ORDER, SHARED_SCHEMA_ORGANIZATIONS=DOMAIN_ONLY), [])
