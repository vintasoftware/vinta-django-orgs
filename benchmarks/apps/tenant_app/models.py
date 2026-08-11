"""The same domain for django-tenants: no tenant column anywhere.

These tables are created once per schema, so each copy only ever holds one
tenant's rows and the indexes carry no tenant key.
"""

from django.db import models


class Author(models.Model):
    name = models.CharField(max_length=100)


class Article(models.Model):
    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name='articles')
    title = models.CharField(max_length=200)
    status = models.CharField(max_length=20)
    views = models.IntegerField(default=0)
    published_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['-published_at']),
        ]


class Comment(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='comments')
    body = models.TextField()
