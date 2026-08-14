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

Each check also narrows with ``active()``, for the same reason the permission
backend does: a deactivated membership is kept for the audit trail and grants
nothing.

These two answer questions about the *selected* organization. For "may this user
do X in organization Y", where Y is named rather than ambient, see
:func:`vinta_orgs.authorization.has_organization_permission`.
"""

from typing import Any

from django.db.models import Model
from rest_framework.permissions import BasePermission, DjangoModelPermissions
from rest_framework.request import Request
from rest_framework.views import APIView

from vinta_orgs.state import organization_state


def _member_of_the_selected_organization(request: Request, **kwargs: Any) -> bool:
    """Whether the caller holds an active membership of the selected organization.

    ``organization_state.get()`` first, and not merely as an optimization. A
    permission check is one place where "no organization selected" has an
    obviously correct answer -- nobody may act in an organization nobody
    selected -- and ``STRICT_ORGANIZATION_FILTER`` would otherwise raise
    ``OrganizationNotFoundError`` out of ``for_current_organization()``, turning
    an unbound request into a 500 where a 403 is what the caller should see.

    ``is_authenticated`` before the query, because ``memberships`` is the
    reverse accessor of a foreign key to the user model and ``AnonymousUser``
    does not carry one. ``has_permission`` already rejects anonymous requests,
    so this only matters to a subclass that turns ``authenticated_users_only``
    off -- which used to get an ``AttributeError`` instead of a 403.
    """
    if organization_state.get() is None:
        return False

    if not request.user.is_authenticated:
        return False

    return bool(request.user.memberships.for_current_organization().active().filter(**kwargs).exists())


class DjangoOrganizationModelPermissions(DjangoModelPermissions):
    def has_object_permission(self, request: Request, view: APIView, obj: Model) -> bool:
        kwargs: dict[str, Any]

        if hasattr(obj, 'organization'):
            kwargs = {'organization': obj.organization}
        elif hasattr(obj, 'organizations'):
            kwargs = {'organization__in': obj.organizations.all()}
        else:
            return True

        return _member_of_the_selected_organization(request, **kwargs)


class IsOrganizationOwner(BasePermission):
    def has_permission(self, request: Request, view: APIView) -> bool:
        return _member_of_the_selected_organization(request, groups__name='organization_owner')

    def has_object_permission(self, request: Request, view: APIView, obj: Model) -> bool:
        kwargs: dict[str, Any]

        if hasattr(obj, 'organization'):
            kwargs = {'organization': obj.organization}
        elif hasattr(obj, 'organizations'):
            kwargs = {'organization__in': obj.organizations.all()}
        else:
            return True

        return _member_of_the_selected_organization(request, **kwargs)
