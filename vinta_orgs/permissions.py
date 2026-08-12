"""Permission classes that answer "may this user act *in this organization*".

Every check here reads ``request.user.memberships`` and then narrows it to the
selected organization with ``for_current_organization()``.

That narrowing used to be implicit: ``OrganizationMembership``'s default manager
scoped, and Django builds reverse accessors from it, so ``user.memberships``
arrived pre-filtered. The manager is deliberately unscoped now -- memberships are
how an organization gets selected in the first place -- which would otherwise
have quietly turned "an owner of the selected organization" into "an owner of
any organization". Spelling it out keeps these exactly as strict as they were,
and puts the requirement where the code that depends on it can be read.
"""

from typing import Any

from django.db.models import Model
from rest_framework.permissions import BasePermission, DjangoModelPermissions
from rest_framework.request import Request
from rest_framework.views import APIView


class DjangoOrganizationModelPermissions(DjangoModelPermissions):
    def has_object_permission(self, request: Request, view: APIView, obj: Model) -> bool:
        kwargs: dict[str, Any]

        if hasattr(obj, 'organization'):
            kwargs = {'organization': obj.organization}
        elif hasattr(obj, 'organizations'):
            kwargs = {'organization__in': obj.organizations.all()}
        else:
            return True

        # ``is_authenticated`` first: ``memberships`` is the reverse accessor of
        # a foreign key to the user model, which ``AnonymousUser`` does not
        # carry. ``has_permission`` already rejects anonymous requests, so this
        # only matters to a subclass that turns ``authenticated_users_only``
        # off -- which used to get an ``AttributeError`` instead of a 403.
        return (
            request.user.is_authenticated
            and request.user.memberships.for_current_organization().filter(**kwargs).exists()
        )


class IsOrganizationOwner(BasePermission):
    def has_permission(self, request: Request, view: APIView) -> bool:
        return (
            request.user.is_authenticated
            and request.user.memberships.for_current_organization().filter(groups__name='organization_owner').exists()
        )

    def has_object_permission(self, request: Request, view: APIView, obj: Model) -> bool:
        kwargs: dict[str, Any]

        if hasattr(obj, 'organization'):
            kwargs = {'organization': obj.organization}
        elif hasattr(obj, 'organizations'):
            kwargs = {'organization__in': obj.organizations.all()}
        else:
            return True

        return (
            request.user.is_authenticated
            and request.user.memberships.for_current_organization().filter(**kwargs).exists()
        )
