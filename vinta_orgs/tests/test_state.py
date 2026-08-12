import threading

from django.test import TestCase
from django.utils.functional import SimpleLazyObject

from vinta_orgs.helpers.organizations import (
    clear_current_organization,
    create_organization,
    get_current_organization,
    organization_context,
    reset_current_organization,
    set_current_organization,
)
from vinta_orgs.models import Organization


class CurrentOrganizationTests(TestCase):
    def setUp(self) -> None:
        self.organization_1 = create_organization(name='organization_1', slug='organization_1')
        self.organization_2 = create_organization(name='organization_2', slug='organization_2')
        clear_current_organization()

    def tearDown(self) -> None:
        clear_current_organization()

    def test_set_by_slug(self) -> None:
        set_current_organization(self.organization_1.slug)
        self.assertEqual(get_current_organization(), self.organization_1)

    def test_set_by_instance(self) -> None:
        set_current_organization(self.organization_1)
        self.assertEqual(get_current_organization(), self.organization_1)

    def test_set_by_slug_does_not_query_until_read(self) -> None:
        with self.assertNumQueries(0):
            set_current_organization(self.organization_1.slug)

        with self.assertNumQueries(1):
            organization = get_current_organization()
            assert organization is not None
            self.assertEqual(organization.name, 'organization_1')

    def test_binding_an_already_lazy_organization_does_not_resolve_it(self) -> None:
        resolutions: list[int] = []

        def resolve() -> Organization:
            resolutions.append(1)
            return self.organization_1

        lazy_organization = SimpleLazyObject(resolve)

        set_current_organization(lazy_organization)

        # This is what the middleware binds on every request; resolving it here
        # would query for an organization the request may never look at.
        self.assertEqual(resolutions, [])
        self.assertEqual(get_current_organization(), self.organization_1)
        self.assertEqual(resolutions, [1])

    def test_clear_without_anything_set_does_not_raise(self) -> None:
        clear_current_organization()
        self.assertIsNone(get_current_organization())

    def test_reset_restores_previous_organization(self) -> None:
        set_current_organization(self.organization_1)
        token = set_current_organization(self.organization_2)

        reset_current_organization(token)

        self.assertEqual(get_current_organization(), self.organization_1)

    def test_unknown_slug_resolves_to_nothing(self) -> None:
        set_current_organization('does-not-exist')
        # A slug is bound lazily, so what comes back is a lazy wrapper around
        # ``None`` rather than ``None`` itself -- falsy either way, which is
        # what every caller checks.
        self.assertFalse(get_current_organization())


class OrganizationContextTests(TestCase):
    def setUp(self) -> None:
        self.organization_1 = create_organization(name='organization_1', slug='organization_1')
        self.organization_2 = create_organization(name='organization_2', slug='organization_2')
        clear_current_organization()

    def tearDown(self) -> None:
        clear_current_organization()

    def test_binds_inside_and_restores_after(self) -> None:
        with organization_context(self.organization_1) as organization:
            self.assertEqual(organization, self.organization_1)
            self.assertEqual(get_current_organization(), self.organization_1)

        self.assertIsNone(get_current_organization())

    def test_restores_previous_organization_instead_of_clearing(self) -> None:
        set_current_organization(self.organization_1)

        with organization_context(self.organization_2):
            self.assertEqual(get_current_organization(), self.organization_2)

        self.assertEqual(get_current_organization(), self.organization_1)

    def test_nesting(self) -> None:
        with organization_context(self.organization_1):
            with organization_context(self.organization_2):
                self.assertEqual(get_current_organization(), self.organization_2)

            self.assertEqual(get_current_organization(), self.organization_1)

    def test_restores_on_exception(self) -> None:
        with self.assertRaises(ValueError):
            with organization_context(self.organization_1):
                raise ValueError()

        self.assertIsNone(get_current_organization())

    def test_works_as_a_decorator(self) -> None:
        @organization_context(self.organization_1)
        def read_organization() -> Organization | None:
            return get_current_organization()

        self.assertEqual(read_organization(), self.organization_1)
        self.assertIsNone(get_current_organization())

    def test_decorator_supports_recursion(self) -> None:
        @organization_context(self.organization_1)
        def countdown(remaining: int) -> Organization | None:
            self.assertEqual(get_current_organization(), self.organization_1)
            if remaining:
                countdown(remaining - 1)
            return get_current_organization()

        self.assertEqual(countdown(3), self.organization_1)
        self.assertIsNone(get_current_organization())

    def test_binding_does_not_leak_into_another_thread(self) -> None:
        seen = []

        def read_organization() -> None:
            seen.append(get_current_organization())

        set_current_organization(self.organization_1)
        thread = threading.Thread(target=read_organization)
        thread.start()
        thread.join()

        self.assertEqual(seen, [None])
