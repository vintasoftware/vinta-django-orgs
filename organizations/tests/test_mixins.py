from typing import Any, cast

from django.contrib.auth.models import User
from django.db import models
from django.test import TestCase, override_settings
from model_bakery import baker

from exampleproject.articles.models import Article, Comment, Tag
from organizations.exceptions import OrganizationNotFoundError
from organizations.helpers.organizations import (
    clear_current_organization,
    create_organization,
    set_current_organization,
)
from organizations.managers import OrganizationScopedManagerMixin
from organizations.mixins import get_default_organization
from organizations.models import OrganizationMembership, OrganizationSite


class SingleOrganizationModelMixinQueryCountTests(TestCase):
    """The scoping must not cost queries of its own.

    Each of these used to be one ``SELECT`` more: the field's callable default
    ran on every instantiation, and ``save()`` read ``self.organization``
    through the descriptor, which fetches the row.
    """

    def setUp(self) -> None:
        self.organization = create_organization(name='organization', slug='organization')
        self.user: User = baker.make(User)
        # Bound as an instance rather than as a slug on purpose. Binding a slug
        # stores a lazy object that resolves on its first use, which is one
        # query per *context* -- what the middleware does once per request --
        # and would land inside whichever assertion here happened to run first.
        set_current_organization(self.organization)

    def test_instantiation_makes_no_queries(self) -> None:
        with self.assertNumQueries(0):
            Article(title='Test Article', text='Test', author=self.user)

    def test_save_makes_a_single_query(self) -> None:
        article = Article(title='Test Article', text='Test', author=self.user)

        with self.assertNumQueries(1):
            article.save()

    def test_save_with_an_explicit_organization_makes_a_single_query(self) -> None:
        article = Article(organization=self.organization, title='Test Article', text='Test', author=self.user)

        with self.assertNumQueries(1):
            article.save()

    def test_bulk_create_makes_a_single_query(self) -> None:
        articles = [
            Article(organization=self.organization, title='Article %d' % i, text='Test', author=self.user)
            for i in range(10)
        ]

        with self.assertNumQueries(1):
            Article.objects.bulk_create(articles)


class SingleOrganizationModelMixinSaveTests(TestCase):
    def setUp(self) -> None:
        self.organization = create_organization(name='organization', slug='organization')
        self.user: User = baker.make(User)

    def test_uses_the_organization_bound_to_the_context(self) -> None:
        set_current_organization(self.organization.slug)
        article = Article.objects.create(title='Test Article', text='Test', author=self.user)

        self.assertEqual(article.organization, self.organization)

    def test_bound_organization_wins_over_the_default_organization(self) -> None:
        # The field used to carry ``default=get_default_organization``, applied
        # at instantiation, so a project that actually had an organization
        # named ``default`` silently saved every row into it instead of into
        # the organization bound to the request.
        create_organization(name='default', slug='default')
        set_current_organization(self.organization.slug)

        article = Article.objects.create(title='Test Article', text='Test', author=self.user)

        self.assertEqual(article.organization, self.organization)

    def test_falls_back_to_the_default_organization(self) -> None:
        default = create_organization(name='default', slug='default')
        clear_current_organization()

        article = Article(title='Test Article', text='Test', author=self.user)
        article.save()

        self.assertEqual(article.organization, default)

    def test_raises_without_a_bound_or_default_organization(self) -> None:
        clear_current_organization()
        article = Article(title='Test Article', text='Test', author=self.user)

        with self.assertRaises(OrganizationNotFoundError):
            article.save()

    def test_keeps_an_explicitly_assigned_organization(self) -> None:
        other = create_organization(name='other', slug='other')
        set_current_organization(self.organization.slug)

        article = Article(organization=other, title='Test Article', text='Test', author=self.user)
        article.save()

        self.assertEqual(article.organization, other)


@override_settings(SHARED_SCHEMA_ORGANIZATIONS={'DEFAULT_ORGANIZATION_SLUG': None})
class NoDefaultOrganizationTests(TestCase):
    """``DEFAULT_ORGANIZATION_SLUG = None`` means "there is no catch-all".

    The setting used to be passed straight into a ``filter()``, so saying "no
    default" still cost a ``WHERE slug IS NULL`` on every save that had no
    organization to fall back on.
    """

    def setUp(self) -> None:
        self.organization = create_organization(name='organization', slug='organization')
        self.user: User = baker.make(User)
        clear_current_organization()

    def test_returns_nothing_without_querying(self) -> None:
        with self.assertNumQueries(0):
            self.assertIsNone(get_default_organization())

    def test_save_raises_without_querying_for_a_default(self) -> None:
        article = Article(title='Test Article', text='Test', author=self.user)

        # ``assertRaises`` inside, so it swallows the exception and
        # ``assertNumQueries`` still gets to make its assertion on the way out.
        with self.assertNumQueries(0), self.assertRaises(OrganizationNotFoundError):
            article.save()

    def test_a_selected_organization_still_wins(self) -> None:
        set_current_organization(self.organization)

        article = Article.objects.create(title='Test Article', text='Test', author=self.user)

        self.assertEqual(article.organization, self.organization)


class BaseManagerTests(TestCase):
    """``_base_manager`` must return every row, on every scoped model.

    Django uses it for the operations that already know the row exists -- the
    ``UPDATE`` behind ``save()``, ``refresh_from_db()``, the cascade collector
    behind ``delete()``, forward relation fetches -- so a scoped one does not
    hide rows, it breaks those operations. It used to be pointed at ``objects``,
    and which models inherited that depended on the order of their base classes.
    """

    scoped_models = [Article, Comment, Tag, OrganizationMembership, OrganizationSite]

    def setUp(self) -> None:
        self.organization = create_organization(name='organization', slug='organization')
        self.user: User = baker.make(User)
        self.article = baker.make(Article, organization=self.organization, author=self.user)
        clear_current_organization()

    def test_base_manager_is_never_the_scoped_manager(self) -> None:
        # Covers both ways of inheriting the mixin. ``Options.base_manager``
        # reads ``base_manager_name`` off the first parent in the MRO that has a
        # ``_meta``, so ``Article``, which inherits the mixin alone, used to pick
        # up the scoped manager while ``OrganizationSite``, which lists
        # ``TimeStampedModel`` first, never saw the attribute at all. The two
        # still resolve to different classes -- ``original_manager`` and the
        # plain ``Manager`` Django creates when nothing is inherited -- but
        # neither scopes, which is the property that matters here.
        for model in self.scoped_models:
            with self.subTest(model=model.__name__):
                self.assertNotIsInstance(model._base_manager, OrganizationScopedManagerMixin)

    def test_base_manager_sees_rows_without_a_selected_organization(self) -> None:
        self.assertEqual(Article._base_manager.filter(pk=self.article.pk).count(), 1)

    def test_resaving_an_instance_updates_it_instead_of_inserting_a_duplicate(self) -> None:
        # The ``UPDATE`` goes through ``_base_manager``. Scoped, it matched no
        # rows, so ``Model._save_table`` decided the row was new and issued an
        # ``INSERT`` -- which failed on the duplicate primary key.
        self.article.title = 'changed'
        self.article.save()

        self.assertEqual(Article.original_manager.count(), 1)
        self.assertEqual(Article.original_manager.get(pk=self.article.pk).title, 'changed')

    def test_refresh_from_db_finds_the_row(self) -> None:
        Article.original_manager.filter(pk=self.article.pk).update(title='changed elsewhere')

        self.article.refresh_from_db()

        self.assertEqual(self.article.title, 'changed elsewhere')

    def test_forward_relation_is_reachable(self) -> None:
        comment = baker.make(Comment, organization=self.organization, article=self.article)
        comment = Comment.original_manager.get(pk=comment.pk)

        self.assertEqual(comment.article, self.article)

    @override_settings(SHARED_SCHEMA_ORGANIZATIONS={'STRICT_ORGANIZATION_FILTER': True})
    def test_strict_filter_leaves_an_explicitly_organized_save_alone(self) -> None:
        article = Article(organization=self.organization, title='Test Article', text='Test', author=self.user)

        article.save()

        self.assertEqual(article.organization, self.organization)

    @override_settings(SHARED_SCHEMA_ORGANIZATIONS={'STRICT_ORGANIZATION_FILTER': True})
    def test_strict_filter_leaves_resaving_and_refreshing_alone(self) -> None:
        self.article.title = 'changed'
        self.article.save()
        self.article.refresh_from_db()

        self.assertEqual(self.article.title, 'changed')

    @override_settings(SHARED_SCHEMA_ORGANIZATIONS={'STRICT_ORGANIZATION_FILTER': True})
    def test_strict_filter_leaves_cascade_deletes_alone(self) -> None:
        # The collector walks the reverse relations through ``_base_manager``,
        # so it used to raise before it could find anything to delete.
        self.organization.delete()

        self.assertEqual(Article.original_manager.count(), 0)


class OrganizationIndexTests(TestCase):
    """Every scoped model needs one index, and only one, leading with the organization."""

    scoped_models = [Article, OrganizationMembership, OrganizationSite]

    def test_organization_column_has_no_index_of_its_own(self) -> None:
        # Django's single-column foreign key index is a prefix of the composite
        # below, so it can answer nothing the composite cannot -- but the
        # planner will choose it and then sort.
        for model in self.scoped_models:
            with self.subTest(model=model.__name__):
                # Asserted through ``deconstruct()`` because that is what the
                # migration writes: ``ForeignKey`` emits ``db_index=False``
                # there precisely when it builds no index of its own.
                field = cast('models.Field[Any, Any]', model._meta.get_field('organization'))
                *_, kwargs = field.deconstruct()

                self.assertFalse(kwargs.get('db_index', True))

    def test_composite_index_leads_with_the_organization(self) -> None:
        for model in self.scoped_models:
            with self.subTest(model=model.__name__):
                fields = [index.fields for index in model._meta.indexes]

                self.assertIn(['organization', model._meta.pk.name], fields)

    def test_index_is_not_added_twice(self) -> None:
        for model in self.scoped_models:
            with self.subTest(model=model.__name__):
                wanted = ['organization', model._meta.pk.name]
                matching = [index for index in model._meta.indexes if index.fields == wanted]

                self.assertEqual(len(matching), 1)
