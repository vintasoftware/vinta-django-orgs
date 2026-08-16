"""Organization ownership is immutable unless a caller opts into relocation."""

from typing import Any

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from exampleproject.articles.models import Article
from vinta_orgs.exceptions import OrganizationCannotBeUpdatedError
from vinta_orgs.tests.factories import clear_current_organization, create_organization


class OrganizationUpdateTests(TestCase):
    def setUp(self) -> None:
        self.organization = create_organization(name='organization', slug='organization')
        self.other = create_organization(name='other', slug='other')
        self.user = User.objects.create_user(username='author')
        self.article = Article.objects.create(
            organization=self.organization, title='title', text='text', author=self.user
        )
        clear_current_organization()

    def assert_article_moved(self) -> None:
        self.article.refresh_from_db()
        self.assertEqual(self.article.organization_id, self.other.pk)

    def test_update_refuses_both_organization_spellings(self) -> None:
        for values in ({'organization': self.other}, {'organization_id': self.other.pk}):
            with self.subTest(values=values), self.assertRaises(OrganizationCannotBeUpdatedError):
                Article.original_manager.filter(pk=self.article.pk).update(**values)

    def test_update_allows_an_explicit_unsafe_relocation(self) -> None:
        Article.original_manager.filter(pk=self.article.pk).update(
            organization=self.other, unsafe_organization_update=True
        )

        self.assert_article_moved()

    async def test_aupdate_obeys_the_same_policy(self) -> None:
        with self.assertRaises(OrganizationCannotBeUpdatedError):
            await Article.original_manager.filter(pk=self.article.pk).aupdate(organization=self.other)

        await Article.original_manager.filter(pk=self.article.pk).aupdate(
            organization=self.other, unsafe_organization_update=True
        )
        await self.article.arefresh_from_db()
        self.assertEqual(self.article.organization_id, self.other.pk)

    def test_save_refuses_relocation_and_unsafe_save_allows_it(self) -> None:
        self.article.organization = self.other

        with self.assertRaises(OrganizationCannotBeUpdatedError):
            self.article.save()

        self.article.save(unsafe_organization_update=True)
        self.assert_article_moved()

    async def test_asave_obeys_the_same_policy(self) -> None:
        self.article.organization = self.other

        with self.assertRaises(OrganizationCannotBeUpdatedError):
            await self.article.asave()

        await self.article.asave(unsafe_organization_update=True)
        await self.article.arefresh_from_db()
        self.assertEqual(self.article.organization_id, self.other.pk)

    def test_bulk_update_refuses_relocation_and_unsafe_bulk_update_allows_it(self) -> None:
        self.article.organization = self.other

        with self.assertRaises(OrganizationCannotBeUpdatedError):
            Article.objects.bulk_update([self.article], ['organization'])

        Article.objects.bulk_update([self.article], ['organization'], unsafe_organization_update=True)
        self.assert_article_moved()

    async def test_abulk_update_obeys_the_same_policy(self) -> None:
        self.article.organization = self.other

        with self.assertRaises(OrganizationCannotBeUpdatedError):
            await Article.objects.abulk_update([self.article], ['organization'])

        await Article.objects.abulk_update([self.article], ['organization'], unsafe_organization_update=True)
        await self.article.arefresh_from_db()
        self.assertEqual(self.article.organization_id, self.other.pk)

    def test_update_or_create_refuses_relocation_and_unsafe_update_or_create_allows_it(self) -> None:
        lookup: dict[str, Any] = {'pk': self.article.pk, 'organization': self.organization}

        with self.assertRaises(OrganizationCannotBeUpdatedError):
            Article.objects.update_or_create(**lookup, defaults={'organization': self.other})

        Article.objects.update_or_create(
            **lookup,
            defaults={'organization': self.other},
            unsafe_organization_update=True,
        )
        self.assert_article_moved()

    async def test_aupdate_or_create_obeys_the_same_policy(self) -> None:
        lookup: dict[str, Any] = {'pk': self.article.pk, 'organization': self.organization}

        with self.assertRaises(OrganizationCannotBeUpdatedError):
            await Article.objects.aupdate_or_create(**lookup, defaults={'organization': self.other})

        await Article.objects.aupdate_or_create(
            **lookup,
            defaults={'organization': self.other},
            unsafe_organization_update=True,
        )
        await self.article.arefresh_from_db()
        self.assertEqual(self.article.organization_id, self.other.pk)

    def test_bulk_create_conflict_updates_need_the_same_opt_in(self) -> None:
        replacement = Article(
            pk=self.article.pk,
            organization=self.other,
            title='replacement',
            text='replacement',
            author=self.user,
        )

        with self.assertRaises(OrganizationCannotBeUpdatedError):
            Article.objects.bulk_create(
                [replacement],
                update_conflicts=True,
                update_fields=['organization'],
                unique_fields=['pk'],
            )

        Article.objects.bulk_create(
            [replacement],
            update_conflicts=True,
            update_fields=['organization'],
            unique_fields=['pk'],
            unsafe_organization_update=True,
        )
        self.assert_article_moved()

    async def test_abulk_create_conflict_updates_obey_the_same_policy(self) -> None:
        replacement = Article(
            pk=self.article.pk,
            organization=self.other,
            title='replacement',
            text='replacement',
            author=self.user,
        )

        with self.assertRaises(OrganizationCannotBeUpdatedError):
            await Article.objects.abulk_create(
                [replacement],
                update_conflicts=True,
                update_fields=['organization'],
                unique_fields=['pk'],
            )

        await Article.objects.abulk_create(
            [replacement],
            update_conflicts=True,
            update_fields=['organization'],
            unique_fields=['pk'],
            unsafe_organization_update=True,
        )
        await self.article.arefresh_from_db()
        self.assertEqual(self.article.organization_id, self.other.pk)


class OrganizationImmutabilityCostTests(TestCase):
    """``save()`` must not read or lock the row to enforce immutability.

    The check asks one question -- did the caller change the organization on a
    row that already exists? An instance loaded from the database carries the
    answer, so asking the database again is redundant. It is also expensive in a
    way nothing local surfaces: under ``ATOMIC_REQUESTS`` Django's
    ``transaction.atomic()`` inside ``save()`` is a *savepoint* in the request's
    transaction, and PostgreSQL does not release row locks when a savepoint is
    released -- only when the transaction commits. A ``SELECT ... FOR UPDATE``
    taken to validate one save is therefore held for the rest of the request,
    across whatever else that request does, including outbound network calls.

    These tests pin the cost, not just the behaviour: reverting to the read
    makes them fail on the query count while every correctness test still
    passes.
    """

    def setUp(self) -> None:
        self.organization = create_organization(name='organization', slug='organization')
        self.other = create_organization(name='other', slug='other')
        self.user = User.objects.create_user(username='cost-author')
        Article.objects.create(organization=self.organization, title='title', text='text', author=self.user)
        clear_current_organization()

    def load(self) -> Article:
        return Article.original_manager.get(title='title')

    def test_saving_a_loaded_row_is_one_statement(self) -> None:
        article = self.load()
        article.title = 'edited'

        # The UPDATE, and nothing else: no SELECT to re-read the organization,
        # and no SAVEPOINT/RELEASE pair around it.
        with self.assertNumQueries(1):
            article.save()

    def test_saving_a_loaded_row_takes_no_row_lock(self) -> None:
        article = self.load()
        article.title = 'edited'

        with CaptureQueriesContext(connection) as captured:
            article.save()

        statements = ' '.join(query['sql'].upper() for query in captured.captured_queries)
        self.assertNotIn('FOR UPDATE', statements)
        self.assertNotIn('SAVEPOINT', statements)

    def test_a_relocation_is_still_refused_without_reading_the_row(self) -> None:
        article = self.load()
        article.organization = self.other

        # The instance already knows the persisted organization, so the refusal
        # needs no query at all.
        with self.assertNumQueries(0), self.assertRaises(OrganizationCannotBeUpdatedError):
            article.save()

        article.refresh_from_db()
        self.assertEqual(article.organization_id, self.organization.pk)

    def test_the_row_is_read_only_when_the_instance_cannot_answer(self) -> None:
        """An instance built in memory with a primary key has no snapshot."""
        constructed = Article(
            pk=self.load().pk,
            organization=self.other,
            title='title',
            text='text',
            author=self.user,
        )

        with self.assertRaises(OrganizationCannotBeUpdatedError):
            constructed.save()

    def test_a_deferred_organization_falls_back_rather_than_guessing(self) -> None:
        article = Article.original_manager.defer('organization').get(title='title')
        article.title = 'edited'

        # ``defer('organization')`` leaves the column out of the load, so there
        # is no snapshot to compare and the fallback read is correct here.
        article.save()

        article.refresh_from_db()
        self.assertEqual(article.organization_id, self.organization.pk)

    def test_an_unsafe_relocation_then_a_plain_save_is_not_refused(self) -> None:
        """The snapshot has to follow a relocation the caller was allowed to make."""
        article = self.load()
        article.organization = self.other
        article.save(unsafe_organization_update=True)

        article.title = 'edited after moving'
        article.save()

        article.refresh_from_db()
        self.assertEqual(article.organization_id, self.other.pk)
        self.assertEqual(article.title, 'edited after moving')

    def test_refresh_from_db_retakes_the_snapshot(self) -> None:
        article = self.load()
        Article.original_manager.filter(pk=article.pk).update(organization=self.other, unsafe_organization_update=True)

        article.refresh_from_db()
        article.title = 'edited'
        article.save()

        article.refresh_from_db()
        self.assertEqual(article.organization_id, self.other.pk)

    def test_a_partial_save_does_not_bless_an_unwritten_organization(self) -> None:
        """``update_fields`` that omits the organization must not update the snapshot.

        Otherwise an in-memory reassignment would be recorded as persisted and
        the next full save would be admitted.
        """
        article = self.load()
        article.title = 'edited'
        article.organization = self.other
        article.save(update_fields=['title'])

        with self.assertRaises(OrganizationCannotBeUpdatedError):
            article.save()
