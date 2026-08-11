from typing import Any

from django.conf import settings as django_settings
from django.contrib.sites.models import Site
from django.db import models
from django.db.models.signals import post_delete
from model_utils.models import TimeStampedModel

from organizations.managers import SingleOrganizationUnscopedManager
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

    # The one scoped model whose default manager must *not* scope.
    #
    # A membership is metadata about the tenancy rather than data inside it: it
    # is the table you read to work out which organization to select, so scoping
    # it to the selected organization is circular. Listing the organizations a
    # user belongs to, provisioning the first membership right after signup, and
    # checking whether an invitation's user is already a member all happen before
    # anything has been selected, and all of them returned nothing -- or raised,
    # under ``STRICT_ORGANIZATION_FILTER``.
    #
    # This is inherited by the reverse accessors as well, which is most of the
    # point: Django builds ``user.memberships`` and ``organization.memberships``
    # from ``_default_manager.__class__``, so they used to carry the scoping into
    # exactly the lookups that cannot work under it.
    #
    # ``SingleOrganizationUnscopedManager`` rather than a plain ``Manager`` so
    # the scoping methods stay available on both the manager and its querysets:
    # ``objects.filter_by_organization(org)`` and
    # ``user.memberships.for_current_organization()`` are how a caller that does
    # want one organization says so. ``organization_objects``, inherited from
    # the mixin, remains implicitly scoped for callers that prefer that.
    #
    # Ignored because narrowing a manager to a *less* capable type is exactly
    # what is intended here: the mixin declares ``objects`` as the scoped
    # manager, and this replaces it with the unscoped one.
    objects = SingleOrganizationUnscopedManager()  # type: ignore[assignment,misc]

    def __str__(self) -> str:
        groups_str = ', '.join([g.name for g in self.groups.all()])
        return '%s - %s (%s)' % (str(self.user), str(self.organization), groups_str)

    class Meta:
        unique_together = [('user', 'organization')]
        # Spelled out rather than left to manager creation order, which would
        # otherwise pick the mixin's ``original_manager`` -- declared earlier,
        # and so with a lower creation counter than the ``objects`` above.
        default_manager_name = 'objects'
