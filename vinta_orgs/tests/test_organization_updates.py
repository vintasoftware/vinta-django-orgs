"""Organization ownership is immutable unless a caller opts into relocation."""

from typing import Any, cast

from django.contrib.auth.models import User
from django.test import TestCase

from exampleproject.articles.models import Article
from vinta_orgs.exceptions import OrganizationCannotBeUpdatedError
from vinta_orgs.helpers.organizations import clear_current_organization, create_organization


class OrganizationUpdateTests(TestCase):
    def setUp(self) -> None:
        self.organization = create_organization(name='organization', slug='organization')
        self.other = create_organization(name='other', slug='other')
        self.user = User.objects.create_user(username='author')
        self.article = Article.objects.create(
            organization=cast('Any', self.organization), title='title', text='text', author=self.user
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
        self.article.organization = cast('Any', self.other)

        with self.assertRaises(OrganizationCannotBeUpdatedError):
            self.article.save()

        self.article.save(unsafe_organization_update=True)
        self.assert_article_moved()

    async def test_asave_obeys_the_same_policy(self) -> None:
        self.article.organization = cast('Any', self.other)

        with self.assertRaises(OrganizationCannotBeUpdatedError):
            await self.article.asave()

        await self.article.asave(unsafe_organization_update=True)
        await self.article.arefresh_from_db()
        self.assertEqual(self.article.organization_id, self.other.pk)

    def test_bulk_update_refuses_relocation_and_unsafe_bulk_update_allows_it(self) -> None:
        self.article.organization = cast('Any', self.other)

        with self.assertRaises(OrganizationCannotBeUpdatedError):
            Article.objects.bulk_update([self.article], ['organization'])

        Article.objects.bulk_update([self.article], ['organization'], unsafe_organization_update=True)
        self.assert_article_moved()

    async def test_abulk_update_obeys_the_same_policy(self) -> None:
        self.article.organization = cast('Any', self.other)

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
            organization=cast('Any', self.other),
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
            organization=cast('Any', self.other),
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
