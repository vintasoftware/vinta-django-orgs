from django.conf import settings
from django.db import models

from organizations.fields import OrganizationSafeForeignKey, OrganizationSafeOneToOneField
from organizations.mixins import MultipleOrganizationsModelMixin, SingleOrganizationModelMixin


class Article(SingleOrganizationModelMixin):
    title = models.CharField(max_length=100)
    text = models.TextField()
    tags = models.ManyToManyField('articles.Tag')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    def __str__(self) -> str:
        return '%s - %s' % (self.title, str(self.author))


class Tag(MultipleOrganizationsModelMixin):
    text = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.text


class Comment(SingleOrganizationModelMixin):
    article = OrganizationSafeForeignKey(Article, on_delete=models.CASCADE, related_name='comments')
    text = models.TextField()

    def __str__(self) -> str:
        return self.text


class ArticleStatistics(SingleOrganizationModelMixin):
    article = OrganizationSafeOneToOneField(Article, on_delete=models.CASCADE, related_name='statistics')
    views = models.IntegerField(default=0)

    def __str__(self) -> str:
        return '%s - %s' % (str(self.article), self.views)
