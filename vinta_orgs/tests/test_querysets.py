from unittest import mock

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase, override_settings
from model_bakery import baker

from exampleproject.articles.models import Article, Comment, Tag
from vinta_orgs.exceptions import OrganizationNotFoundError
from vinta_orgs.tests.factories import (
    clear_current_organization,
    create_organization,
    set_current_organization,
)


class SingleOrganizationQuerySetTests(TestCase):
    def setUp(self) -> None:
        self.organization_1 = create_organization(name='organization_1', slug='organization_1')
        self.organization_2 = create_organization(name='organization_2', slug='organization_2')

        baker.make(Article, organization=self.organization_1, _quantity=5)
        baker.make(Article, organization=self.organization_2, _quantity=3)

        # The instance rather than the slug so nothing under test pays for
        # resolving a lazily bound organization.
        set_current_organization(self.organization_1)

    def tearDown(self) -> None:
        clear_current_organization()

    def test_manager_filter_by_organization_ignores_the_bound_organization(self) -> None:
        self.assertEqual(Article.objects.filter_by_organization(self.organization_2).count(), 3)

    def test_manager_exclude_by_organization_ignores_the_bound_organization(self) -> None:
        self.assertEqual(Article.objects.exclude_by_organization(self.organization_2).count(), 5)

    def test_scoping_chains_after_other_lookups(self) -> None:
        queryset = Article.original_manager.filter(text__isnull=False)

        self.assertEqual(queryset.filter_by_organization(self.organization_2).count(), 3)
        self.assertEqual(queryset.exclude_by_organization(self.organization_2).count(), 5)

    def test_for_current_organization_chains_after_other_lookups(self) -> None:
        queryset = Article.original_manager.filter(text__isnull=False)

        self.assertEqual(queryset.for_current_organization().count(), 5)

    def test_an_unbound_scoped_query_raises(self) -> None:
        clear_current_organization()

        with self.assertRaises(OrganizationNotFoundError):
            Article.original_manager.all().for_current_organization().count()

        with self.assertRaises(OrganizationNotFoundError):
            Article.objects.count()

    @override_settings(SHARED_SCHEMA_ORGANIZATIONS={'STRICT_ORGANIZATION_FILTER': False})
    def test_for_current_organization_is_empty_without_a_bound_organization_when_not_strict(self) -> None:
        clear_current_organization()

        self.assertEqual(Article.original_manager.all().for_current_organization().count(), 0)

    def test_strict_filter_leaves_explicitly_scoped_queries_alone(self) -> None:
        clear_current_organization()

        self.assertEqual(Article.objects.filter_by_organization(self.organization_2).count(), 3)
        self.assertEqual(Article.original_manager.count(), 8)

    def test_unscoped_returns_every_organization(self) -> None:
        self.assertEqual(Article.objects.unscoped().count(), 8)
        self.assertEqual(Article.objects.get_original_queryset().count(), 8)

    def test_with_organization_fetches_organizations_in_the_same_query(self) -> None:
        with self.assertNumQueries(1):
            names = [article.organization.name for article in Article.objects.with_organization()]

        self.assertEqual(names, ['organization_1'] * 5)

    def test_without_with_organization_each_row_costs_a_query(self) -> None:
        with self.assertNumQueries(6):
            [article.organization.name for article in Article.objects.all()]


class MultipleOrganizationsQuerySetTests(TestCase):
    def setUp(self) -> None:
        self.organization_1 = create_organization(name='organization_1', slug='organization_1')
        self.organization_2 = create_organization(name='organization_2', slug='organization_2')

        # ``MultipleOrganizationsModelMixin.save`` attaches whichever
        # organization is bound, so each batch is created under its own.
        set_current_organization(self.organization_1)
        self.tags_1 = baker.make(Tag, _quantity=5)

        set_current_organization(self.organization_2)
        self.tags_2 = baker.make(Tag, _quantity=3)

        set_current_organization(self.organization_1)

    def tearDown(self) -> None:
        clear_current_organization()

    def test_manager_filter_by_organization_ignores_the_bound_organization(self) -> None:
        self.assertEqual(Tag.objects.filter_by_organization(self.organization_2).count(), 3)

    def test_manager_exclude_by_organization_ignores_the_bound_organization(self) -> None:
        self.assertEqual(Tag.objects.exclude_by_organization(self.organization_2).count(), 5)

    def test_scoping_chains_after_other_lookups(self) -> None:
        queryset = Tag.original_manager.filter(text__isnull=False)

        self.assertEqual(queryset.filter_by_organization(self.organization_2).count(), 3)
        self.assertEqual(queryset.for_current_organization().count(), 5)

    def test_with_organizations_prefetches_in_a_single_extra_query(self) -> None:
        with self.assertNumQueries(2):
            organizations = [list(tag.organizations.all()) for tag in Tag.objects.with_organizations()]

        self.assertEqual(organizations, [[self.organization_1]] * 5)


class AutoDeferSafeJoinTests(TestCase):
    """A paged ``select_related`` over a safe relation is split into two queries.

    The join matches on the organization as well as on the key, and PostgreSQL
    underestimates it by roughly the number of organizations, which costs it the
    ordered index walk. Fetching the related rows separately sidesteps the
    estimate entirely. See ``benchmarks/RESULTS.md``.
    """

    def setUp(self) -> None:
        self.organization = create_organization(name='organization', slug='organization')
        set_current_organization(self.organization)
        self.user: User = baker.make(User)
        self.articles = baker.make(Article, organization=self.organization, author=self.user, _quantity=3)

        for article in self.articles:
            baker.make(Comment, organization=self.organization, article=article, _quantity=2)

    def tearDown(self) -> None:
        clear_current_organization()

    def test_paged_select_related_stays_a_single_query(self) -> None:
        with self.assertNumQueries(1) as ctx:
            comments = list(Comment.objects.select_related('article').order_by('id')[:4])

        self.assertEqual(len(comments), 4)
        # The page is collected by the subquery and the join is handed those
        # rows, rather than the join being computed and then cut down to a page.
        self.assertIn('IN (SELECT', ctx.captured_queries[0]['sql'])

    def test_falls_back_to_a_second_query_where_sliced_subqueries_are_unsupported(self) -> None:
        # MySQL cannot put a sliced subquery inside ``IN``.
        with mock.patch.object(connection.features, 'allow_sliced_subqueries_with_in', False):
            with self.assertNumQueries(2):
                fallback = list(Comment.objects.select_related('article').order_by('id')[:4])

            with self.assertNumQueries(0):
                [comment.article.pk for comment in fallback]

        subquery = list(Comment.objects.select_related('article').order_by('id')[:4])

        self.assertEqual([c.pk for c in fallback], [c.pk for c in subquery])

    def test_deferred_join_still_populates_the_relation(self) -> None:
        comments = list(Comment.objects.select_related('article').order_by('id')[:4])

        # Reading the relation must not go back to the database, which is the
        # whole point of having asked for it up front.
        with self.assertNumQueries(0):
            organizations = {comment.article.organization_id for comment in comments}

        self.assertEqual(organizations, {self.organization.pk})

    def test_deferred_join_returns_the_same_rows_as_the_join(self) -> None:
        with self.settings(SHARED_SCHEMA_ORGANIZATIONS={'AUTO_DEFER_SAFE_JOINS': False}):
            joined = [c.pk for c in Comment.objects.select_related('article').order_by('id')[:4]]

        deferred = [c.pk for c in Comment.objects.select_related('article').order_by('id')[:4]]

        self.assertEqual(deferred, joined)

    def test_setting_turns_it_off(self) -> None:
        with self.settings(SHARED_SCHEMA_ORGANIZATIONS={'AUTO_DEFER_SAFE_JOINS': False}):
            with self.assertNumQueries(1) as ctx:
                list(Comment.objects.select_related('article').order_by('id')[:4])

        # Straight back to joining first and cutting the result down to a page.
        self.assertNotIn('IN (SELECT', ctx.captured_queries[0]['sql'])

    def test_unpaged_select_related_still_joins(self) -> None:
        # Without a LIMIT there is no early exit to lose, so the join is left
        # alone rather than traded for a second round trip.
        with self.assertNumQueries(1):
            list(Comment.objects.select_related('article').order_by('id'))

    def test_plain_foreign_keys_are_left_alone(self) -> None:
        # ``Article.author`` is an ordinary foreign key: it joins on the key
        # alone, so the planner estimates it correctly and the join is the
        # cheapest way to fetch it.
        with self.assertNumQueries(1):
            list(Article.objects.select_related('author').order_by('id')[:3])

    def test_select_related_with_no_arguments_is_left_alone(self) -> None:
        with self.assertNumQueries(1):
            list(Comment.objects.select_related().order_by('id')[:4])


class FilterRelatedWithoutJoinTests(TestCase):
    """Filtering across a safe relation by testing each row instead of joining."""

    def setUp(self) -> None:
        self.organization = create_organization(name='organization', slug='organization')
        self.other = create_organization(name='other', slug='other')
        set_current_organization(self.organization)
        self.user = baker.make(User)
        self.published = baker.make(Article, organization=self.organization, author=self.user, title='published')
        self.draft = baker.make(Article, organization=self.organization, author=self.user, title='draft')
        baker.make(Comment, organization=self.organization, article=self.published, _quantity=2)
        baker.make(Comment, organization=self.organization, article=self.draft)

    def tearDown(self) -> None:
        clear_current_organization()

    def test_matches_the_same_rows_as_the_join(self) -> None:
        joined = Comment.objects.filter(article__title='published').order_by('id')
        walked = Comment.objects.filter_related_without_join(article__title='published').order_by('id')

        self.assertEqual([c.pk for c in walked], [c.pk for c in joined])
        self.assertEqual(len(walked), 2)

    def test_does_not_join_to_the_related_table(self) -> None:
        sql = str(Comment.objects.filter_related_without_join(article__title='published').query)

        self.assertIn('EXISTS', sql)
        self.assertNotIn('INNER JOIN', sql)

    def test_fences_the_subquery_on_postgresql(self) -> None:
        # The fence is what makes the planner walk the rows in order; on other
        # backends ``OFFSET`` without ``LIMIT`` is not even valid.
        with mock.patch.object(connection, 'vendor', 'postgresql'):
            fenced = str(Comment.objects.filter_related_without_join(article__title='published').query)

        unfenced = str(Comment.objects.filter_related_without_join(article__title='published').query)

        self.assertIn('OFFSET 0', fenced)
        self.assertNotIn('OFFSET 0', unfenced)

    def test_does_not_match_another_organizations_target(self) -> None:
        # The comment's own organization is the one bound; its article belongs
        # to another. The safe relation would not join it, and neither does this.
        stray = Comment.objects.create(article=self.published, text='stray')
        Comment.objects.filter(pk=stray.pk).update(
            article_fk=baker.make(Article, organization=self.other, author=self.user, title='published')
        )

        matched = Comment.objects.filter_related_without_join(article__title='published')

        self.assertNotIn(stray.pk, [c.pk for c in matched])

    def test_combines_several_lookups_into_one_subquery(self) -> None:
        sql = str(Comment.objects.filter_related_without_join(article__title='published', article__text='').query)

        self.assertEqual(sql.count('EXISTS'), 1)

    def test_rejects_a_relation_that_is_not_organization_safe(self) -> None:
        with self.assertRaises(ValueError):
            Comment.objects.filter_related_without_join(plain_article__title='published')

    def test_rejects_a_lookup_that_does_not_cross_the_relation(self) -> None:
        with self.assertRaises(ValueError):
            Comment.objects.filter_related_without_join(article=self.published)
