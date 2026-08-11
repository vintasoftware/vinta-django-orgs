from typing import Any

import django.utils.version
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from model_bakery import baker

from exampleproject.articles.models import Article, Tag
from organizations.exceptions import OrganizationNotFoundError
from organizations.helpers.organizations import (
    clear_current_organization,
    create_organization,
    set_current_organization,
)
from organizations.models import OrganizationMembership


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

    def test_return_nothing_if_no_organization_set_or_passed(self) -> None:
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

    def test_return_nothing_if_no_organization_set_or_passed(self) -> None:
        clear_current_organization()
        self.assertEqual(self.tags_manager.all().count(), 0)


class NoneTests(TestCase):
    """``objects.none()`` must not need an organization to be selected.

    It asks for no rows, so it cannot leak any -- but it used to go through
    ``get_queryset()`` like every other generated manager method, and so raised
    under ``STRICT_ORGANIZATION_FILTER``.
    """

    # ``OrganizationMembership`` is in here because the library's own model is
    # the one a project is most likely to call this on outside a request.
    #
    # Annotated ``list[Any]`` rather than ``list[type[Model]]`` because these are
    # read through ``objects``, which ``Model`` itself does not declare.
    scoped_models: list[Any] = [Article, Tag, OrganizationMembership]

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
