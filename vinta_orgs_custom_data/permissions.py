from typing import Any

from rest_framework import exceptions
from rest_framework.permissions import DjangoModelPermissions
from rest_framework.request import Request
from rest_framework.views import APIView

from vinta_orgs_custom_data.models import OrganizationSpecificTable


class DjangoOrganizationSpecificTablePermissions(DjangoModelPermissions):
    organization_specific_tables_perms_map = {
        'GET': [],
        'OPTIONS': [],
        'HEAD': [],
        'POST': ['add_%(model_name)s'],
        'PUT': ['change_%(model_name)s'],
        'PATCH': ['change_%(model_name)s'],
        'DELETE': ['delete_%(model_name)s'],
    }

    authenticated_users_only = True

    def get_required_table_permissions(self, method: str | None, table_id: int) -> list[str]:
        """The permission codes a user needs to call ``method`` on this table.

        Named apart from ``DjangoModelPermissions.get_required_permissions``
        rather than overriding it: that one takes a queryset and is called by
        the base ``has_permission``, so redefining it with a different second
        argument left the inherited method unusable.
        """
        table = OrganizationSpecificTable.objects.get(id=table_id)

        kwargs = {
            'model_name': table.name,
        }

        if method not in self.perms_map:
            raise exceptions.MethodNotAllowed(str(method))

        return [perm % kwargs for perm in self.organization_specific_tables_perms_map[method]]

    def _queryset(self, view: APIView) -> Any:
        """The view's queryset.

        Typed loosely on purpose: this permission class is only meaningful on a
        view serving custom table rows, whose queryset carries the ``table_id``
        read below. ``queryset`` itself is a ``GenericAPIView`` attribute, not
        an ``APIView`` one, which is why the assertion checks for it.
        """
        assert hasattr(view, 'get_queryset') or getattr(view, 'queryset', None) is not None, (
            f'Cannot apply {self.__class__.__name__} on a view that does not set '
            '`.queryset` or have a `.get_queryset()` method.'
        )

        if hasattr(view, 'get_queryset'):
            queryset = view.get_queryset()
            assert queryset is not None, f'{view.__class__.__name__}.get_queryset() returned None'
            return queryset
        # ``queryset`` is a ``GenericAPIView`` attribute, and the assertion at
        # the top of this method already established that this view has one.
        assert hasattr(view, 'queryset')
        return view.queryset

    def has_permission(self, request: Request, view: APIView) -> bool:
        if getattr(view, '_ignore_model_permissions', False):
            return True

        if not request.user or (not request.user.is_authenticated and self.authenticated_users_only):
            return False

        queryset = self._queryset(view)
        perms = self.get_required_table_permissions(request.method, queryset.table_id)

        return request.user.has_perms(perms)
