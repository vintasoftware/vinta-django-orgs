from typing import Any

import django.utils.version
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from model_bakery import baker

from exampleproject.articles.models import Article, Tag
from vinta_orgs.conf import get_organization_membership_model
from vinta_orgs.exceptions import OrganizationNotFoundError
from vinta_orgs.helpers.organizations import (
    clear_current_organization,
    set_current_organization,
)
from vinta_orgs.tests.factories import create_organization


class SingleOrganizationModelManagerTests(TestCase):
    def setUp(self) -> None:
        self.organization_1 = create_organization(name='organization_1', slug='organization_1')
        self.organization_2 = create_organization(name='organization_2', slug='organization_2')

        self.articles_t1 = baker.make(Article, organization=self.organization_1, _quantity=5)
        self.articles_t2 = baker.make(Article, organization=self.organization_2, _quantity=3)

        set_current_organization(self.organization_1.slug)

        self.articles_manager = Article.objects
        if django.utils.version.get_complete_version()[1] < 10:
            self.articles_manager = Article.organization_objects

    def test_create(self) -> None:
        user = baker.make(User)
        article = self.articles_manager.create(title='Test Article', text='Test Article Description', author=user)

        self.assertEqual(article.organization, self.organization_1)

    def test_create_raise_exception_if_no_organization_set_or_passed(self) -> None:
        clear_current_organization()
        user = baker.make(User)
        with self.assertRaises(OrganizationNotFoundError):
            self.articles_manager.create(title='Test Article', text='Test Article Description', author=user)

    def test_create_passing_organization(self) -> None:
        user = baker.make(User)
        article = self.articles_manager.create(
            organization=self.organization_1, title='Test Article', text='Test Article Description', author=user
        )

        self.assertEqual(article.organization, self.organization_1)

    def test_list(self) -> None:
        self.assertEqual(self.articles_manager.count(), self.organization_1.article_set.count())
        set_current_organization(self.organization_2.slug)
        self.assertEqual(self.articles_manager.count(), self.organization_2.article_set.count())

    def test_list_passing_organization_to_get_queryset(self) -> None:
        self.assertEqual(
            self.articles_manager.get_queryset(organization=self.organization_1).all().count(),
            self.organization_1.article_set.all().count(),
        )
        self.assertEqual(
            self.articles_manager.get_queryset(organization=self.organization_2).all().count(),
            self.articles_manager.get_queryset(organization=self.organization_2).all().count(),
            self.organization_2.article_set.all().count(),
        )

    def test_list_original_queryset(self) -> None:
        self.assertEqual(self.articles_manager.get_original_queryset().all().count(), 8)

    def test_raise_if_no_organization_set_or_passed(self) -> None:
        clear_current_organization()

        with self.assertRaises(OrganizationNotFoundError):
            self.articles_manager.all().count()

    @override_settings(SHARED_SCHEMA_ORGANIZATIONS={'STRICT_ORGANIZATION_FILTER': False})
    def test_return_nothing_if_no_organization_set_or_passed_and_not_strict(self) -> None:
        clear_current_organization()
        self.assertEqual(self.articles_manager.all().count(), 0)


class MultipleOrganizationModelManagerTests(TestCase):
    def setUp(self) -> None:
        self.organization_1 = create_organization(name='organization_1', slug='organization_1')
        self.organization_2 = create_organization(name='organization_2', slug='organization_2')

        set_current_organization(self.organization_1.slug)
        self.tags_t1 = baker.make(Tag, _quantity=5)
        self.shared_tags = baker.make(Tag, organizations=[self.organization_1, self.organization_2], _quantity=7)
        set_current_organization(self.organization_2.slug)
        self.tags_t2 = baker.make(Tag, _quantity=3)
        for tag in self.shared_tags:
            tag.save()

        set_current_organization(self.organization_1.slug)

        self.tags_manager = Tag.objects
        if django.utils.version.get_complete_version()[1] < 10:
            self.tags_manager = Tag.organization_objects

    def test_create(self) -> None:
        tag = self.tags_manager.create(text='Test tag')
        self.assertIn(self.organization_1, tag.organizations.all())

    def test_create_raise_exception_if_no_organization_set_or_passed(self) -> None:
        clear_current_organization()
        with self.assertRaises(OrganizationNotFoundError):
            self.tags_manager.create(text='Test tag')

    def test_list(self) -> None:
        self.assertEqual(self.tags_manager.count(), len(self.tags_t1) + len(self.shared_tags))
        set_current_organization(self.organization_2)
        self.assertEqual(self.tags_manager.count(), len(self.tags_t2) + len(self.shared_tags))

    def test_list_passing_organization_to_get_queryset(self) -> None:
        self.assertEqual(
            self.tags_manager.get_queryset(organization=self.organization_1).all().count(),
            len(self.tags_t1) + len(self.shared_tags),
        )
        self.assertEqual(
            self.tags_manager.get_queryset(organization=self.organization_2).all().count(),
            len(self.tags_t2) + len(self.shared_tags),
        )

    def test_list_original_queryset(self) -> None:
        self.assertEqual(
            self.tags_manager.get_original_queryset().all().count(),
            len(self.tags_t1) + len(self.tags_t2) + len(self.shared_tags),
        )

    def test_raise_if_no_organization_set_or_passed(self) -> None:
        clear_current_organization()

        with self.assertRaises(OrganizationNotFoundError):
            self.tags_manager.all().count()

    @override_settings(SHARED_SCHEMA_ORGANIZATIONS={'STRICT_ORGANIZATION_FILTER': False})
    def test_return_nothing_if_no_organization_set_or_passed_and_not_strict(self) -> None:
        clear_current_organization()
        self.assertEqual(self.tags_manager.all().count(), 0)


class NoneTests(TestCase):
    """``objects.none()`` must not need an organization to be selected.

    It asks for no rows, so it cannot leak any -- but it used to go through
    ``get_queryset()`` like every other generated manager method, and so raised
    under ``STRICT_ORGANIZATION_FILTER``.
    """

    # The membership model is in here because the library's own is the one a
    # project is most likely to call this on outside a request. Resolved rather
    # than imported so the swapped run exercises the project's own model.
    #
    # Annotated ``list[Any]`` rather than ``list[type[Model]]`` because these are
    # read through ``objects``, which ``Model`` itself does not declare.
    scoped_models: list[Any] = [Article, Tag, get_organization_membership_model()]

    def setUp(self) -> None:
        self.organization = create_organization(name='organization', slug='organization')
        baker.make(Article, organization=self.organization, _quantity=3)
        clear_current_organization()

    def test_none_is_empty_without_a_selected_organization(self) -> None:
        for model in self.scoped_models:
            with self.subTest(model=model.__name__):
                self.assertEqual(model.objects.none().count(), 0)

    @override_settings(SHARED_SCHEMA_ORGANIZATIONS={'STRICT_ORGANIZATION_FILTER': True})
    def test_strict_filter_leaves_none_alone(self) -> None:
        for model in self.scoped_models:
            with self.subTest(model=model.__name__):
                self.assertEqual(model.objects.none().count(), 0)

    def test_none_is_empty_with_a_selected_organization(self) -> None:
        set_current_organization(self.organization)

        self.assertEqual(Article.objects.count(), 3)
        self.assertEqual(Article.objects.none().count(), 0)

    def test_none_makes_no_queries(self) -> None:
        # ``QuerySet.none()`` marks the query empty rather than running it, and
        # taking the unscoped queryset must not change that.
        with self.assertNumQueries(0):
            list(Article.objects.none())


class CreateTests(TestCase):
    """``objects.create()`` reads no rows, so it must not need one selected.

    ``Manager.create`` is generated as ``self.get_queryset().create(...)``, and
    under ``STRICT_ORGANIZATION_FILTER`` that scoping raised before the
    ``INSERT`` ever ran -- including for a call that named its organization
    outright, and for every ``instance.related_set.create(...)``, which Django
    routes through the same method.
    """

    def setUp(self) -> None:
        self.organization = create_organization(name='organization', slug='organization')
        self.other_organization = create_organization(name='other', slug='other')
        self.user = User.objects.create_user(username='author', password='x')
        clear_current_organization()

    def test_create_with_an_explicit_organization_needs_nothing_selected(self) -> None:
        article = Article.objects.create(organization=self.organization, title='t', text='x', author=self.user)

        self.assertEqual(article.organization, self.organization)

    def test_create_still_takes_the_selected_organization_when_given_none(self) -> None:
        set_current_organization(self.other_organization)

        article = Article.objects.create(title='t', text='x', author=self.user)

        self.assertEqual(article.organization, self.other_organization)

    def test_create_still_raises_when_no_organization_can_be_resolved(self) -> None:
        # ``save()`` is what refuses, not the queryset -- so the guarantee is
        # unchanged and only the point at which the caller finds out moves.
        with (
            override_settings(SHARED_SCHEMA_ORGANIZATIONS={'DEFAULT_ORGANIZATION_SLUG': None}),
            self.assertRaises(OrganizationNotFoundError),
        ):
            Article.objects.create(title='t', text='x', author=self.user)

    def test_a_related_manager_create_needs_nothing_selected(self) -> None:
        organization_site = self.organization.organization_sites.create(
            site=baker.make('sites.Site', domain='create.example')
        )

        self.assertEqual(organization_site.organization, self.organization)

    def test_bulk_create_needs_nothing_selected(self) -> None:
        articles = [
            Article(organization=self.organization, title='a', text='x', author=self.user),
            Article(organization=self.organization, title='b', text='x', author=self.user),
        ]

        Article.objects.bulk_create(articles)

        self.assertEqual(Article.original_manager.filter_by_organization(self.organization).count(), 2)

    def test_get_or_create_is_deliberately_not_relaxed(self) -> None:
        # The dangerous one: it *looks a row up*, and with nothing selected that
        # lookup spans every organization -- so it can hand back somebody
        # else's row and let the caller write to it.
        with self.assertRaises(OrganizationNotFoundError):
            Article.objects.get_or_create(title='t', defaults={'text': 'x', 'author': self.user})
