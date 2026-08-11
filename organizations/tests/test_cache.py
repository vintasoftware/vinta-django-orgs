"""The site -> organization mapping is cached, and invalidated when it changes."""

from __future__ import annotations

from django.contrib.sites.models import Site
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings

from organizations.helpers.organizations import clear_current_organization, create_organization
from organizations.models import Organization, OrganizationSite
from organizations.organization_retrievers import retrieve_by_domain

CACHING = {'CACHE_ORGANIZATION_RETRIEVAL': True}


class OrganizationRetrievalCacheTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.organization = create_organization(name='test', slug='test', domains=['test.localhost:8000'])
        clear_current_organization()

    def tearDown(self) -> None:
        cache.clear()

    def _retrieve(self) -> Organization | None:
        request = RequestFactory().get('/', HTTP_HOST='test.localhost:8000')
        return retrieve_by_domain(request)

    def test_off_by_default(self) -> None:
        self._retrieve()

        with self.assertNumQueries(1):
            self.assertEqual(self._retrieve(), self.organization)

    @override_settings(SHARED_SCHEMA_ORGANIZATIONS=CACHING)
    def test_second_retrieval_costs_no_query(self) -> None:
        self.assertEqual(self._retrieve(), self.organization)

        with self.assertNumQueries(0):
            cached = self._retrieve()

        assert cached is not None
        self.assertEqual(cached, self.organization)
        self.assertEqual(cached.slug, self.organization.slug)
        self.assertEqual(cached.name, self.organization.name)

    @override_settings(SHARED_SCHEMA_ORGANIZATIONS=CACHING)
    def test_unmapped_domain_is_cached_too(self) -> None:
        Site.objects.create(domain='unmapped.localhost:8000', name='unmapped')
        request = RequestFactory().get('/', HTTP_HOST='unmapped.localhost:8000')

        self.assertIsNone(retrieve_by_domain(request))

        with self.assertNumQueries(0):
            self.assertIsNone(retrieve_by_domain(request))

    @override_settings(SHARED_SCHEMA_ORGANIZATIONS=CACHING)
    def test_renaming_the_organization_invalidates_it(self) -> None:
        self._retrieve()

        self.organization.name = 'renamed'
        self.organization.save()

        renamed = self._retrieve()

        assert renamed is not None
        self.assertEqual(renamed.name, 'renamed')

    @override_settings(SHARED_SCHEMA_ORGANIZATIONS=CACHING)
    def test_reassigning_the_domain_invalidates_it(self) -> None:
        self._retrieve()

        other = create_organization(name='other', slug='other')
        organization_site = OrganizationSite.original_manager.get(site__domain='test.localhost:8000')
        organization_site.organization = other
        organization_site.save()

        self.assertEqual(self._retrieve(), other)

    @override_settings(SHARED_SCHEMA_ORGANIZATIONS=CACHING)
    def test_deleting_the_mapping_invalidates_it(self) -> None:
        self._retrieve()

        OrganizationSite.original_manager.get(site__domain='test.localhost:8000').delete()

        self.assertIsNone(self._retrieve())

    @override_settings(SHARED_SCHEMA_ORGANIZATIONS=CACHING)
    def test_a_cache_written_before_a_migration_reads_as_a_miss(self) -> None:
        from organizations.cache import cache_key, get_cache

        # Column set no longer matching the model: reconstructing half an
        # instance would be worse than going back to the database.
        site = Site.objects.get(domain='test.localhost:8000')
        get_cache().set(cache_key(site.pk), {'slug': 'test', 'gone': 1})

        self.assertEqual(self._retrieve(), self.organization)
