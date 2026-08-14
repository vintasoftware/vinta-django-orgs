"""Callable adapters for migration and test-runner integration."""

from django.contrib.auth.models import Group

from vinta_orgs.models import AbstractOrganization
from vinta_orgs.services import OrganizationService


def create_default_organization_groups() -> list[Group]:
    """Run the default service seeder through a dotted-path-compatible callable."""
    service: OrganizationService[AbstractOrganization] = OrganizationService()
    return service.create_default_groups()
