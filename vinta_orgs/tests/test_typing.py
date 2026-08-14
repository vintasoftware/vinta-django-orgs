"""Static assertions for the public swapped-model API.

The function below is never called. ``mypy`` checks its body against the
project's concrete replacement models, while the runtime suites simply import
this module without touching the database.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import assert_type

    from django.contrib.auth.models import User
    from django.db.models import QuerySet
    from django.http import HttpRequest

    from exampleproject.customorgs.models import Organization as CustomOrganization
    from exampleproject.customorgs.models import OrganizationMembership as CustomOrganizationMembership
    from vinta_orgs.conf import get_organization_membership_model, get_organization_model
    from vinta_orgs.middleware import OrganizationRequest, get_organization
    from vinta_orgs.models import AbstractOrganization, AbstractOrganizationMembership
    from vinta_orgs.services import MembershipService, OrganizationService
    from vinta_orgs.state import OrganizationState

    class ProjectOrganizationService(OrganizationService[CustomOrganization]):
        model_class = CustomOrganization

    class ProjectMembershipService(MembershipService[CustomOrganization, CustomOrganizationMembership]):
        model_class = CustomOrganizationMembership

    class ProjectOrganizationState(OrganizationState[CustomOrganization]):
        model_class = CustomOrganization

    def _assert_swapped_model_types(
        organization: CustomOrganization,
        membership: CustomOrganizationMembership,
        user: User,
        request: OrganizationRequest[CustomOrganization],
        plain_request: HttpRequest,
    ) -> None:
        assert_type(get_organization_model(CustomOrganization), type[CustomOrganization])
        assert_type(
            get_organization_membership_model(CustomOrganizationMembership),
            type[CustomOrganizationMembership],
        )
        assert_type(get_organization_model(), type[AbstractOrganization])
        assert_type(get_organization_membership_model(), type[AbstractOrganizationMembership])

        assert_type(request.organization, CustomOrganization | None)
        assert_type(get_organization(request), CustomOrganization | None)
        assert_type(get_organization(plain_request), AbstractOrganization | None)

        organization_state = ProjectOrganizationState()
        assert_type(organization_state, ProjectOrganizationState)
        assert_type(organization_state.model, type[CustomOrganization])
        assert_type(organization_state.get(), CustomOrganization | None)

        with organization_state.context(organization) as current:
            assert_type(current, CustomOrganization | None)

        with organization_state.context('acme') as current:
            assert_type(current, CustomOrganization | None)

        organization_service = ProjectOrganizationService()
        membership_service = ProjectMembershipService()

        assert_type(organization_service, ProjectOrganizationService)
        assert_type(membership_service, ProjectMembershipService)
        assert_type(organization_service.model, type[CustomOrganization])
        assert_type(organization_service.create('Acme', 'acme'), CustomOrganization)
        assert_type(organization_service.update(organization), CustomOrganization)
        assert_type(membership_service.model, type[CustomOrganizationMembership])
        assert_type(membership_service.organization_model, type[CustomOrganization])
        assert_type(membership_service.create(organization, user), CustomOrganizationMembership)
        assert_type(membership_service.get_active(user), QuerySet[CustomOrganizationMembership])
        assert_type(
            membership_service.resolve_for_user(user),
            CustomOrganizationMembership | None,
        )
        assert_type(
            membership_service.resolve_organization_for_user(user),
            CustomOrganization | None,
        )

        # Keep both concrete parameters live so a future simplification cannot
        # accidentally turn one of them into an unconstrained ``Any``.
        assert_type(membership, CustomOrganizationMembership)
