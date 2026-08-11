from typing import Any

from django.conf import settings as django_settings
from django.contrib.sites.models import Site
from django.db import models
from django.db.models.signals import post_delete
from model_utils.models import TimeStampedModel

from organizations.mixins import SingleOrganizationModelMixin


class Organization(TimeStampedModel):
    name = models.CharField(max_length=255)
    slug = models.CharField(max_length=255, unique=True)

    def __str__(self) -> str:
        return self.name


class OrganizationSite(TimeStampedModel, SingleOrganizationModelMixin):
    # Redeclared only to name the reverse accessor; ``db_index=False`` keeps it
    # in step with the mixin, whose ``(organization, pk)`` index makes Django's
    # single-column one redundant.
    organization = models.ForeignKey(
        'Organization', related_name='organization_sites', on_delete=models.CASCADE, db_index=False
    )
    site = models.OneToOneField(Site, related_name='organization_site', on_delete=models.CASCADE)

    def __str__(self) -> str:
        return '%s - %s' % (self.organization.name, self.site.domain)


def post_delete_organization_site(
    sender: type[OrganizationSite], instance: OrganizationSite, *args: Any, **kwargs: Any
) -> None:
    if instance.site:
        instance.site.delete()


post_delete.connect(post_delete_organization_site, sender=OrganizationSite)


class OrganizationMembership(TimeStampedModel, SingleOrganizationModelMixin):
    organization = models.ForeignKey(
        'Organization', related_name='memberships', on_delete=models.CASCADE, db_index=False
    )
    user = models.ForeignKey(django_settings.AUTH_USER_MODEL, related_name='memberships', on_delete=models.CASCADE)
    groups = models.ManyToManyField('auth.Group', related_name='user_organization_groups', blank=True)
    permissions = models.ManyToManyField('auth.Permission', related_name='user_organization_permissions', blank=True)

    def __str__(self) -> str:
        groups_str = ', '.join([g.name for g in self.groups.all()])
        return '%s - %s (%s)' % (str(self.user), str(self.organization), groups_str)

    class Meta:
        unique_together = [('user', 'organization')]
