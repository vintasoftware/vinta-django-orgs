"""A project's own organization and membership models, for the swapped test run.

This is what a real project does with ``ORGANIZATION_MODEL`` and
``ORGANIZATION_MEMBERSHIP_MODEL``: inherit the abstract bases, add the fields the
product actually needs, and stop maintaining a one-to-one companion for them.

The extra fields here are the ones that pushed vinta-saas-template into building
companion models in the first place -- a parent organization for reseller
hierarchies, a flag for who may invite other organizations, and a soft-delete
marker on the membership. ``parent`` in particular is why this matters: as a real
column it can take part in a database constraint, which it cannot do from a
separate table.
"""

from django.db import models

from organizations.models import AbstractOrganization, AbstractOrganizationMembership


class Organization(AbstractOrganization):
    parent = models.ForeignKey('self', null=True, blank=True, related_name='children', on_delete=models.PROTECT)
    can_invite_organizations = models.BooleanField(default=False)

    class Meta(AbstractOrganization.Meta):
        constraints = [
            # The point of the exercise: ``name`` and ``parent`` are columns on
            # one table, so uniqueness among siblings is enforceable here. Split
            # across an organization and a profile model it was not.
            models.UniqueConstraint(fields=['parent', 'name'], name='uniq_organization_name_per_parent'),
        ]


class OrganizationMembership(AbstractOrganizationMembership):
    is_active = models.BooleanField(default=True)

    class Meta(AbstractOrganizationMembership.Meta):
        pass
