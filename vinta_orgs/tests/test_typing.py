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
    from vinta_orgs.helpers.memberships import (
        create_membership,
        get_active_memberships,
        resolve_membership_for_user,
        resolve_organization_for_user,
    )
    from vinta_orgs.helpers.organizations import create_organization, update_organization
    from vinta_orgs.middleware import OrganizationMiddleware, OrganizationRequest, get_organization
    from vinta_orgs.models import AbstractOrganization, AbstractOrganizationMembership
    from vinta_orgs.services import MembershipService, OrganizationService
    from vinta_orgs.state import get_current_organization, organization_context

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

        assert_type(
            create_organization('Acme', 'acme', organization_model=CustomOrganization),
            CustomOrganization,
        )
        assert_type(update_organization(organization, name='New name'), CustomOrganization)

        assert_type(
            create_membership(organization, user, membership_model=CustomOrganizationMembership),
            CustomOrganizationMembership,
        )
        assert_type(
            get_active_memberships(user, membership_model=CustomOrganizationMembership),
            QuerySet[CustomOrganizationMembership],
        )
        assert_type(
            resolve_membership_for_user(user, membership_model=CustomOrganizationMembership),
            CustomOrganizationMembership | None,
        )
        assert_type(
            resolve_organization_for_user(user, organization_model=CustomOrganization),
            CustomOrganization | None,
        )

        assert_type(get_current_organization(CustomOrganization), CustomOrganization | None)
        assert_type(
            OrganizationMiddleware.get_current_organization(CustomOrganization),
            CustomOrganization | None,
        )
        assert_type(request.organization, CustomOrganization | None)
        assert_type(get_organization(request), CustomOrganization | None)
        assert_type(get_organization(plain_request), AbstractOrganization | None)

        with organization_context(organization) as current:
            assert_type(current, CustomOrganization | None)

        with organization_context('acme') as current:
            assert_type(current, AbstractOrganization | None)

        organization_service = OrganizationService(CustomOrganization)
        membership_service = MembershipService(organization_service, CustomOrganizationMembership)

        assert_type(organization_service, OrganizationService[CustomOrganization])
        assert_type(
            membership_service,
            MembershipService[CustomOrganization, CustomOrganizationMembership],
        )
        assert_type(organization_service.model, type[CustomOrganization])
        assert_type(organization_service.create('Acme', 'acme'), CustomOrganization)
        assert_type(organization_service.update(organization), CustomOrganization)
        assert_type(organization_service.get_current(), CustomOrganization | None)
        assert_type(organization_service.resolve_for_user(user), CustomOrganization | None)
        assert_type(membership_service.model, type[CustomOrganizationMembership])
        assert_type(membership_service.create(organization, user), CustomOrganizationMembership)
        assert_type(membership_service.get_active(user), QuerySet[CustomOrganizationMembership])
        assert_type(
            membership_service.resolve_for_user(user),
            CustomOrganizationMembership | None,
        )

        # Keep both concrete parameters live so a future simplification cannot
        # accidentally turn one of them into an unconstrained ``Any``.
        assert_type(membership, CustomOrganizationMembership)
