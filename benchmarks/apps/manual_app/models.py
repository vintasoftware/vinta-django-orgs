"""The same domain with a hand-written tenant column and no library.

The tenant key mirrors ``vinta_orgs.Organization``: an implicit integer
primary key with the slug as a unique field. Keying this differently would
measure the key type as much as the approach.
"""

from django.db import models


class Tenant(models.Model):
    slug = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=255)


class Author(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='authors')
    name = models.CharField(max_length=100)


class Article(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='articles')
    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name='articles')
    title = models.CharField(max_length=200)
    status = models.CharField(max_length=20)
    views = models.IntegerField(default=0)
    published_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', '-published_at']),
        ]


class Comment(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='comments')
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='comments')
    body = models.TextField()

    class Meta:
        indexes = [
            models.Index(fields=['tenant', 'article']),
            models.Index(fields=['tenant', 'id']),
        ]
