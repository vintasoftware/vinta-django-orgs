"""Django call paths that need a scoped manager's explicit escape hatches."""

from typing import Any, cast
from unittest import mock

from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.core.exceptions import ValidationError
from django.db import models
from django.test import TestCase

from exampleproject.articles.models import Article, Comment, Tag
from vinta_orgs.exceptions import OrganizationNotFoundError
from vinta_orgs.helpers.organizations import clear_current_organization, create_organization, set_current_organization
from vinta_orgs.managers import unscoped_default_manager
from vinta_orgs.models import OrganizationSite


class RelatedManagerIntegrationTests(TestCase):
    def setUp(self) -> None:
        self.organization = create_organization(name='organization', slug='organization')
        self.other = create_organization(name='other', slug='other')
        self.user = User.objects.create_user(username='author')
        self.article = Article.objects.create(
            organization=cast('Any', self.organization), title='title', text='text', author=self.user
        )
        self.comment = Comment.objects.create(article=self.article, text='comment')
        clear_current_organization()

    def test_reverse_manager_uses_the_source_instance_without_an_ambient_organization(self) -> None:
        self.assertEqual(list(self.article.comments.all()), [self.comment])

    def test_reverse_manager_ignores_a_different_ambient_organization(self) -> None:
        set_current_organization(self.other)

        self.assertEqual(list(self.article.comments.all()), [self.comment])

    def test_prefetch_uses_the_related_instance_scope(self) -> None:
        article = Article.original_manager.prefetch_related('comments').get(pk=self.article.pk)

        with self.assertNumQueries(0):
            self.assertEqual(list(article.comments.all()), [self.comment])


class ScopedManagerEscapeTests(TestCase):
    def setUp(self) -> None:
        self.organization = create_organization(name='organization', slug='organization')
        self.other = create_organization(name='other', slug='other')
        self.user = User.objects.create_user(username='author')
        self.articles = [
            Article.objects.create(
                organization=cast('Any', organization), title=organization.slug, text='text', author=self.user
            )
            for organization in (self.organization, self.other)
        ]
        clear_current_organization()

    def test_context_manager_unscopes_only_its_block(self) -> None:
        with self.assertRaises(OrganizationNotFoundError):
            Article.objects.count()

        with unscoped_default_manager():
            self.assertEqual(Article.objects.count(), 2)

        with self.assertRaises(OrganizationNotFoundError):
            Article.objects.count()

    def test_context_manager_restores_after_an_exception(self) -> None:
        with self.assertRaises(RuntimeError):
            with unscoped_default_manager():
                raise RuntimeError('boom')

        with self.assertRaises(OrganizationNotFoundError):
            Article.objects.count()

    def test_foreign_key_formfield_can_be_built_outside_a_tenant(self) -> None:
        field = Comment._meta.get_field('article_fk')

        with self.assertRaises(OrganizationNotFoundError):
            field.formfield()

        with unscoped_default_manager():
            formfield = field.formfield()

        assert formfield is not None
        self.assertEqual(cast('Any', formfield).queryset.count(), 2)

    def test_bulk_update_uses_instance_primary_keys_without_a_bound_organization(self) -> None:
        for article in self.articles:
            article.text = 'changed'

        Article.objects.bulk_update(self.articles, ['text'])

        self.assertEqual(Article.original_manager.filter(text='changed').count(), 2)

    def test_get_or_create_with_an_explicit_organization_is_unbound_safe(self) -> None:
        article, created = Article.objects.get_or_create(
            organization=cast('Any', self.organization),
            title='new',
            defaults={'text': 'text', 'author': self.user},
        )

        self.assertTrue(created)
        self.assertEqual(article.organization_id, self.organization.pk)


class ValidationIntegrationTests(TestCase):
    def setUp(self) -> None:
        self.organization = create_organization(name='organization', slug='organization')
        self.other = create_organization(name='other', slug='other')
        self.site = Site.objects.create(name='site', domain='site.example')
        OrganizationSite.objects.create(organization=cast('Any', self.organization), site=self.site)
        clear_current_organization()

    def test_validate_unique_uses_the_unscoped_default_manager(self) -> None:
        duplicate = OrganizationSite(organization=cast('Any', self.other), site=self.site)

        with self.assertRaises(ValidationError):
            duplicate.validate_unique()

    def test_validate_constraints_temporarily_unscopes_single_organization_models(self) -> None:
        article = Article(organization=cast('Any', self.organization))

        def validate_constraints(instance: models.Model, exclude: Any = None) -> None:
            self.assertEqual(Article.objects.count(), 0)

        with mock.patch.object(models.Model, 'validate_constraints', validate_constraints):
            article.validate_constraints()

    def test_validate_constraints_temporarily_unscopes_multiple_organization_models(self) -> None:
        tag = Tag()

        def validate_constraints(instance: models.Model, exclude: Any = None) -> None:
            self.assertEqual(Tag.objects.count(), 0)

        with mock.patch.object(models.Model, 'validate_constraints', validate_constraints):
            tag.validate_constraints()
