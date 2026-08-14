"""Concrete service bindings shared by the default and swapped-model suites."""

from __future__ import annotations

from typing import TYPE_CHECKING

from vinta_orgs.conf import get_organization_membership_model, get_organization_model
from vinta_orgs.resolution import UNRESOLVED_ORGANIZATION as UNRESOLVED_ORGANIZATION
from vinta_orgs.services import MembershipService, OrganizationService
from vinta_orgs.state import organization_state

if TYPE_CHECKING:
    # Static checks use tests.settings; the runtime suite also runs with
    # tests.settings_swapped, where the branches below resolve those models.
    from vinta_orgs.models import Organization, OrganizationMembership
else:
    Organization = get_organization_model()
    OrganizationMembership = get_organization_membership_model()

organizations: OrganizationService[Organization] = OrganizationService()
memberships: MembershipService[Organization, OrganizationMembership] = MembershipService()

# Bound methods retain the concrete service generics without introducing a
# second, less precisely typed helper implementation.
create_organization = organizations.create
update_organization = organizations.update
create_default_organization_groups = organizations.create_default_groups
create_membership = memberships.create
get_active_memberships = memberships.get_active
resolve_membership_for_user = memberships.resolve_for_user
resolve_organization_for_user = memberships.resolve_organization_for_user
get_current_organization = organization_state.get
set_current_organization = organization_state.set
clear_current_organization = organization_state.clear
reset_current_organization = organization_state.reset
organization_context = organization_state.context
