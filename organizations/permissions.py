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
        return request.user.is_authenticated and request.user.memberships.filter(**kwargs).exists()


class IsOrganizationOwner(BasePermission):
    def has_permission(self, request: Request, view: APIView) -> bool:
        return (
            request.user.is_authenticated
            and request.user.memberships.filter(groups__name='organization_owner').exists()
        )

    def has_object_permission(self, request: Request, view: APIView, obj: Model) -> bool:
        kwargs: dict[str, Any]

        if hasattr(obj, 'organization'):
            kwargs = {'organization': obj.organization}
        elif hasattr(obj, 'organizations'):
            kwargs = {'organization__in': obj.organizations.all()}
        else:
            return True

        return request.user.is_authenticated and request.user.memberships.filter(**kwargs).exists()
