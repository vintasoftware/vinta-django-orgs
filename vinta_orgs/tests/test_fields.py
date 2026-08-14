from django.contrib.auth.models import User
from django.db import connection, models
from django.test import TestCase
from django.test.utils import isolate_apps

from exampleproject.articles.models import Article, ArticleStatistics, Comment
from vinta_orgs.exceptions import OrganizationCannotBeUpdatedError
from vinta_orgs.fields import OrganizationSafeForeignKey, expand_safe_relation_field_names
from vinta_orgs.tests.factories import (
    clear_current_organization,
    create_organization,
    organization_context,
)


class OrganizationSafeForeignKeyTests(TestCase):
    def setUp(self) -> None:
        self.organization_1 = create_organization(name='organization_1', slug='organization_1')
        self.organization_2 = create_organization(name='organization_2', slug='organization_2')
        self.user = User.objects.create_user(username='test')

        with organization_context(self.organization_1):
            self.article_1 = Article.objects.create(title='article_1', text='t', author=self.user)
            self.comment = Comment.objects.create(article=self.article_1, text='c')

        with organization_context(self.organization_2):
            self.article_2 = Article.objects.create(title='article_2', text='t', author=self.user)

    def tearDown(self) -> None:
        clear_current_organization()

    def _point_comment_at(self, article: Article) -> None:
        """Repoint the comment behind the ORM's back, as a bad write would."""
        with connection.cursor() as cursor:
            cursor.execute(
                'UPDATE articles_comment SET article_fk_id = %s WHERE id = %s', [article.id, self.comment.id]
            )

    def test_declaring_the_field_contributes_both_halves(self) -> None:
        self.assertEqual(Comment._meta.get_field('article_fk').column, 'article_fk_id')
        # The safe relation owns the good name and no column of its own.
        self.assertIsNone(Comment._meta.get_field('article').column)

    def test_organization_is_part_of_the_join_condition(self) -> None:
        with organization_context(self.organization_1):
            sql = str(Comment.objects.select_related('article').query)

        self.assertIn(
            'INNER JOIN "articles_article" ON ("articles_comment"."article_fk_id" = '
            '"articles_article"."id" AND "articles_comment"."organization_id" = '
            '"articles_article"."organization_id")',
            sql,
        )

    def test_filter_traversal_joins_on_the_organization(self) -> None:
        with organization_context(self.organization_1):
            sql = str(Comment.objects.filter(article__title='article_1').query)

        self.assertIn('"articles_comment"."organization_id" = "articles_article"."organization_id"', sql)

    def test_reverse_accessor_matches_on_the_organization(self) -> None:
        with organization_context(self.organization_1):
            self.assertIn('"articles_comment"."organization_id"', str(self.article_1.comments.all().query))
            self.assertEqual(self.article_1.comments.count(), 1)

    def test_a_matching_relation_reads_normally(self) -> None:
        with organization_context(self.organization_1):
            comment = Comment.objects.select_related('article').get(pk=self.comment.pk)

            self.assertEqual(comment.article, self.article_1)
            self.assertEqual(Comment.objects.filter(article=self.article_1).count(), 1)
            self.assertEqual(Comment.objects.filter(article__title='article_1').count(), 1)

    def test_a_cross_organization_row_does_not_join(self) -> None:
        self._point_comment_at(self.article_2)

        with organization_context(self.organization_1):
            # The row still exists, but the relation no longer resolves: it
            # reads as missing rather than as the other organization's article.
            self.assertEqual(Comment.objects.count(), 1)
            self.assertEqual(list(Comment.objects.select_related('article')), [])
            self.assertEqual(Comment.objects.filter(article__title='article_2').count(), 0)
            self.assertEqual(Comment.objects.filter(article=self.article_2).count(), 0)

    def test_a_cross_organization_relation_raises_instead_of_returning_the_row(self) -> None:
        self._point_comment_at(self.article_2)

        with organization_context(self.organization_1):
            comment = Comment.objects.get(pk=self.comment.pk)

            with self.assertRaises(Article.DoesNotExist):
                _ = comment.article


class OrganizationSafeRelationWritesTests(TestCase):
    def setUp(self) -> None:
        self.organization_1 = create_organization(name='organization_1', slug='organization_1')
        self.organization_2 = create_organization(name='organization_2', slug='organization_2')
        self.user = User.objects.create_user(username='test')

        with organization_context(self.organization_1):
            self.article_1 = Article.objects.create(title='article_1', text='t', author=self.user)

        with organization_context(self.organization_2):
            self.article_2 = Article.objects.create(title='article_2', text='t', author=self.user)

    def tearDown(self) -> None:
        clear_current_organization()

    def test_constructing_with_the_instance_writes_the_concrete_field(self) -> None:
        with organization_context(self.organization_1):
            comment = Comment(article=self.article_1, text='c')

            self.assertEqual(comment.article_fk_id, self.article_1.id)

    def test_constructing_with_the_instance_carries_the_organization_over(self) -> None:
        # Nothing is bound, so the organization can only have come from the
        # article -- which is the point: the two cannot drift apart.
        comment = Comment(article=self.article_2, text='c')

        self.assertEqual(comment.organization_id, self.organization_2.pk)

    @isolate_apps()
    def test_nullable_relation_none_keeps_the_organization(self) -> None:
        class TestOrganization(models.Model):  # noqa: DJ008
            class Meta:
                app_label = 'nullable_relation_tests'

        class Target(models.Model):  # noqa: DJ008
            organization = models.ForeignKey(TestOrganization, on_delete=models.CASCADE)

            class Meta:
                app_label = 'nullable_relation_tests'

        class Source(models.Model):  # noqa: DJ008
            organization = models.ForeignKey(TestOrganization, on_delete=models.CASCADE)
            target = OrganizationSafeForeignKey(Target, on_delete=models.CASCADE, null=True)

            class Meta:
                app_label = 'nullable_relation_tests'

        organization = TestOrganization(pk=1)
        target = Target(pk=1, organization=organization)
        organization_field = Source._meta.get_field('organization')
        target_field = Source._meta.get_field('target_fk')
        assert isinstance(organization_field, models.Field)
        assert isinstance(target_field, models.Field)

        constructed = Source(organization=organization, target=None)
        self.assertEqual(organization_field.value_from_object(constructed), organization.pk)
        self.assertIsNone(target_field.value_from_object(constructed))

        constructed.target = target
        constructed.target = None

        self.assertEqual(organization_field.value_from_object(constructed), organization.pk)
        self.assertIsNone(target_field.value_from_object(constructed))
        self.assertIsNone(constructed.target)

    def test_constructing_with_an_id_writes_the_concrete_field(self) -> None:
        with organization_context(self.organization_1):
            # ``article_id`` is exactly what this test exists to cover:
            # ``SingleOrganizationModelMixin.__init__`` rewrites it onto
            # ``article_fk_id``. The model has no such field of its own, which
            # is what django-stubs is reporting.
            comment = Comment(article_id=self.article_1.id, text='c')  # type: ignore[misc]

            self.assertEqual(comment.article_fk_id, self.article_1.id)

    def test_create_and_assignment(self) -> None:
        with organization_context(self.organization_1):
            comment = Comment.objects.create(article=self.article_1, text='c')
            self.assertEqual(comment.article_fk_id, self.article_1.id)

            other = Comment(text='c2')
            other.article = self.article_1
            other.save()
            self.assertEqual(other.article_fk_id, self.article_1.id)

    def test_update_through_the_safe_relation(self) -> None:
        with organization_context(self.organization_1):
            comment = Comment.objects.create(article=self.article_1, text='c')
            other_article = Article.objects.create(title='other', text='t', author=self.user)

            Comment.objects.filter(pk=comment.pk).update(article=other_article)
            comment.refresh_from_db()
            self.assertEqual(comment.article_fk_id, other_article.id)

            Comment.objects.filter(pk=comment.pk).update(article_id=self.article_1.id)
            comment.refresh_from_db()
            self.assertEqual(comment.article_fk_id, self.article_1.id)

    def test_save_with_update_fields_naming_the_safe_relation(self) -> None:
        with organization_context(self.organization_1):
            comment = Comment.objects.create(article=self.article_1, text='c')
            other_article = Article.objects.create(title='other', text='t', author=self.user)

            comment.article = other_article
            comment.save(update_fields=['article'])

            comment.refresh_from_db()
            self.assertEqual(comment.article, other_article)

    def test_save_with_update_fields_refuses_to_move_the_organization(self) -> None:
        with organization_context(self.organization_1):
            comment = Comment.objects.create(article=self.article_1, text='c')

            # Reassigning across organizations moves the row wholesale rather
            # than persisting the key alone, which would leave it pointing
            # across organizations and unreadable through the relation.
            # Saved while organization_1 is still bound, since the UPDATE goes
            # through the scoped base manager and has to match the row as it
            # currently stands.
            comment.article = self.article_2
            with self.assertRaisesMessage(OrganizationCannotBeUpdatedError, '`organization` cannot be updated.'):
                comment.save(update_fields=['article'])

            comment.save(update_fields=['article'], unsafe_organization_update=True)

        comment = Comment.original_manager.get(pk=comment.pk)
        self.assertEqual(comment.organization_id, self.organization_2.pk)

        with organization_context(self.organization_2):
            self.assertEqual(Comment.objects.get(pk=comment.pk).article, self.article_2)

    def test_bulk_update_naming_the_safe_relation(self) -> None:
        with organization_context(self.organization_1):
            comments = [Comment.objects.create(article=self.article_1, text='c%s' % i) for i in range(3)]
            other_article = Article.objects.create(title='other', text='t', author=self.user)

            for comment in comments:
                comment.article = other_article

            Comment.objects.bulk_update(comments, ['article'])

            self.assertEqual(Comment.objects.filter(article=other_article).count(), 3)

    def test_expanding_field_names_leaves_ordinary_fields_alone(self) -> None:
        self.assertEqual(
            expand_safe_relation_field_names(Comment, ['text', 'article']), ['text', 'article_fk', 'organization']
        )
        self.assertEqual(
            expand_safe_relation_field_names(Comment, ['article', 'organization']), ['article_fk', 'organization']
        )
        self.assertEqual(expand_safe_relation_field_names(Article, ['title']), ['title'])

    def test_update_of_ordinary_fields_is_untouched(self) -> None:
        with organization_context(self.organization_1):
            comment = Comment.objects.create(article=self.article_1, text='c')

            Comment.objects.filter(pk=comment.pk).update(text='changed')
            comment.refresh_from_db()

            self.assertEqual(comment.text, 'changed')


class OrganizationSafeOneToOneFieldTests(TestCase):
    def setUp(self) -> None:
        self.organization_1 = create_organization(name='organization_1', slug='organization_1')
        self.organization_2 = create_organization(name='organization_2', slug='organization_2')
        self.user = User.objects.create_user(username='test')

        with organization_context(self.organization_1):
            self.article_1 = Article.objects.create(title='article_1', text='t', author=self.user)
            self.statistics = ArticleStatistics.objects.create(article=self.article_1, views=3)

        with organization_context(self.organization_2):
            self.article_2 = Article.objects.create(title='article_2', text='t', author=self.user)

    def tearDown(self) -> None:
        clear_current_organization()

    def test_organization_is_part_of_the_join_condition(self) -> None:
        with organization_context(self.organization_1):
            sql = str(ArticleStatistics.objects.select_related('article').query)

        self.assertIn('"articles_articlestatistics"."organization_id" = "articles_article"."organization_id"', sql)

    def test_one_to_one_reads_normally(self) -> None:
        with organization_context(self.organization_1):
            statistics = ArticleStatistics.objects.select_related('article').get(pk=self.statistics.pk)

            self.assertEqual(statistics.article, self.article_1)
            self.assertEqual(self.article_1.statistics.views, 3)

    def test_a_cross_organization_row_does_not_join(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                'UPDATE articles_articlestatistics SET article_fk_id = %s WHERE id = %s',
                [self.article_2.id, self.statistics.id],
            )

        with organization_context(self.organization_1):
            self.assertEqual(list(ArticleStatistics.objects.select_related('article')), [])

    def test_reverse_one_to_one_is_organization_checked(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                'UPDATE articles_articlestatistics SET article_fk_id = %s WHERE id = %s',
                [self.article_2.id, self.statistics.id],
            )

        with organization_context(self.organization_1):
            with self.assertRaises(ArticleStatistics.DoesNotExist):
                _ = self.article_1.statistics
