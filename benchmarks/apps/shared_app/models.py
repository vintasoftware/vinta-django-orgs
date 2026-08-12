"""The benchmark's domain, modelled with ``django-shared-schema-organizations``.

Every row carries an ``organization`` and every read goes through the scoped
managers. ``Comment`` deliberately points at ``Article`` twice -- once through
an organization-safe relation and once through a plain foreign key -- so the
suite can price the extra ``AND organization_id = …`` the safe relation puts in
the JOIN's ON clause against the relation that does not have it.
"""

from django.db import models

from vinta_orgs.fields import OrganizationSafeForeignKey
from vinta_orgs.mixins import SingleOrganizationModelMixin


class Author(SingleOrganizationModelMixin):
    name = models.CharField(max_length=100)

    class Meta(SingleOrganizationModelMixin.Meta):
        pass


class Article(SingleOrganizationModelMixin):
    author = OrganizationSafeForeignKey(Author, related_name='articles')
    title = models.CharField(max_length=200)
    status = models.CharField(max_length=20)
    views = models.IntegerField(default=0)
    published_at = models.DateTimeField()

    class Meta(SingleOrganizationModelMixin.Meta):
        # A shared-schema table is only as fast as its composite indexes: the
        # organization column has to lead, or every lookup scans rows belonging
        # to every other tenant. Schema-per-tenant gets the equivalent for free
        # because its tables only ever hold one tenant's rows, so leaving these
        # out would benchmark a misconfiguration rather than the approach.
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['organization', '-published_at']),
        ]


class Comment(SingleOrganizationModelMixin):
    article = OrganizationSafeForeignKey(Article, related_name='comments')
    plain_article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='plain_comments')
    body = models.TextField()

    class Meta(SingleOrganizationModelMixin.Meta):
        indexes = [
            models.Index(fields=['organization', 'article_fk']),
            # Ordering by id under an organization filter needs the
            # organization to lead the index too. Without this the query walks
            # the primary key in id order and discards every other tenant's
            # rows as it goes, which is a missing index rather than a property
            # of shared-schema tenancy -- and benchmarking it would report the
            # wrong thing.
            models.Index(fields=['organization', 'id']),
        ]
