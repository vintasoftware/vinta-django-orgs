"""The organization models, and the abstract bases a project can extend instead.

``Organization`` and ``OrganizationMembership`` are swappable. A project that
needs a field on either -- a parent organization, a reseller flag, a
deactivated-member marker -- declares its own model on the matching abstract
base and points a setting at it, rather than hanging a one-to-one companion off
the concrete model and threading ``select_related`` through every query that
touches it. See :mod:`vinta_orgs.conf`.

``OrganizationSite`` is deliberately not swappable: it exists to map a
``Site`` to an organization, which is not a thing projects extend, and it is
what the retriever and the cache are wired to.
"""

from typing import Any

from django.conf import settings as django_settings
from django.contrib.sites.models import Site
from django.db import models
from django.db.models.signals import post_delete
from model_utils.models import TimeStampedModel

from vinta_orgs.conf import organization_model_string
from vinta_orgs.managers import OrganizationMembershipUnscopedManager
from vinta_orgs.mixins import SingleOrganizationModelMixin


class AbstractOrganization(TimeStampedModel):
    """Everything an organization must have. Inherit this to add your own.

    Subclasses are responsible for nothing but their extra fields -- the name,
    the slug and the timestamps are here, and the rest of the library only ever
    reaches for those.
    """

    name = models.CharField(max_length=255)
    slug = models.CharField(max_length=255, unique=True)

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return self.name


class Organization(AbstractOrganization):
    """The organization model used unless ``ORGANIZATION_MODEL`` says otherwise."""

    class Meta(AbstractOrganization.Meta):
        # Django reads this as the name of a top-level setting. When it names a
        # different model, this one is marked swapped: no table is created for
        # it and the admin refuses to register it.
        swappable = 'ORGANIZATION_MODEL'


class OrganizationSite(TimeStampedModel, SingleOrganizationModelMixin):
    # Redeclared only to name the reverse accessor; ``db_index=False`` keeps it
    # in step with the mixin, whose ``(organization, pk)`` index makes Django's
    # single-column one redundant.
    organization = models.ForeignKey(
        organization_model_string(), related_name='organization_sites', on_delete=models.CASCADE, db_index=False
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


class AbstractOrganizationMembership(TimeStampedModel, SingleOrganizationModelMixin):
    """Everything a membership must have. Inherit this to add your own."""

    organization = models.ForeignKey(
        organization_model_string(), related_name='memberships', on_delete=models.CASCADE, db_index=False
    )
    user = models.ForeignKey(django_settings.AUTH_USER_MODEL, related_name='memberships', on_delete=models.CASCADE)
    groups = models.ManyToManyField('auth.Group', related_name='user_organization_groups', blank=True)
    permissions = models.ManyToManyField('auth.Permission', related_name='user_organization_permissions', blank=True)

    # The membership's soft delete, and the base's because every consumer needs
    # it to mean the same thing.
    #
    # Removing a member without deleting the row is what almost every project
    # does -- you want the audit trail, and the invitations, the audit rows and
    # the billing seats all point at it. Left to each project, the field is a
    # *marker* rather than a *gate*: the permission backend knew nothing about
    # it, so a deactivated administrator kept resolving every permission their
    # groups carried, through ``has_perm`` and through every DRF permission
    # class built on it. That is the widest grant there is, arrived at by an
    # operation whose whole premise is that it takes rights away.
    #
    # The alternative -- a ``get_membership_queryset()`` hook, so a project
    # supplies its own predicate -- puts a security decision in the hands of
    # every consumer and fails silently when they leave it alone. This is a
    # migration for existing projects; silent privilege retention is worse.
    #
    # The gate lives in the lookup (see
    # ``OrganizationModelBackend._get_membership``) rather than in a "clear the
    # groups when a membership is deactivated" side effect: deactivation happens
    # on more than one code path, a cleared-groups approach has to be remembered
    # on every one of them, and reactivation would then need a restore step that
    # knows what to put back. A filter cannot be forgotten.
    is_active = models.BooleanField(
        default=True,
        help_text=(
            'Unset this instead of deleting the row. An inactive membership grants nothing: it resolves no '
            'permissions and cannot be selected as the request organization.'
        ),
    )

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
    # ``OrganizationMembershipUnscopedManager`` rather than a plain ``Manager``
    # so the scoping methods stay available on both the manager and its
    # querysets: ``objects.filter_by_organization(org)`` and
    # ``user.memberships.for_current_organization()`` are how a caller that does
    # want one organization says so, and ``active()`` /
    # ``holding_permission(...)`` are how it asks the two membership-shaped
    # questions. ``organization_objects``, inherited from the mixin, remains
    # implicitly scoped for callers that prefer that.
    #
    # Ignored because narrowing a manager to a *less* capable type is exactly
    # what is intended here: the mixin declares ``objects`` as the scoped
    # manager, and this replaces it with the unscoped one.
    objects = OrganizationMembershipUnscopedManager()  # type: ignore[assignment,misc]

    class Meta:
        abstract = True
        # Emptied by a subclass that needs its own named constraint in place of
        # this one -- five raw-SQL foreign keys binding to a constraint *by
        # name* is the case that forced it once. ``unique_together = []``
        # alongside a ``UniqueConstraint(fields=['user', 'organization'],
        # name=...)`` in the subclass's ``Meta`` keeps the guarantee and moves
        # the name under the project's control. See ``docs/usage.rst``.
        unique_together = [('user', 'organization')]
        # Spelled out rather than left to manager creation order, which would
        # otherwise pick the mixin's ``original_manager`` -- declared earlier,
        # and so with a lower creation counter than the ``objects`` above.
        default_manager_name = 'objects'

    def __str__(self) -> str:
        groups_str = ', '.join([g.name for g in self.groups.all()])
        return '%s - %s (%s)' % (str(self.user), str(self.organization), groups_str)


class OrganizationMembership(AbstractOrganizationMembership):
    """The membership model used unless ``ORGANIZATION_MEMBERSHIP_MODEL`` says otherwise."""

    class Meta(AbstractOrganizationMembership.Meta):
        swappable = 'ORGANIZATION_MEMBERSHIP_MODEL'
