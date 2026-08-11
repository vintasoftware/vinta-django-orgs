from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import QuerySet
from rest_framework import generics, permissions
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from organizations.helpers.organizations import get_current_organization
from organizations.models import Organization, OrganizationSite
from organizations.permissions import DjangoOrganizationModelPermissions
from organizations.settings import get_setting
from organizations.utils import import_from_string

if TYPE_CHECKING:
    # The protocol DRF's own ``get_permissions`` is declared to return. It only
    # exists in the type stubs, so it is never imported at runtime.
    from rest_framework.permissions import _SupportsHasPermission


class OrganizationListView(generics.ListCreateAPIView):
    permission_classes = [DjangoOrganizationModelPermissions]

    def get_permissions(self) -> Sequence[_SupportsHasPermission]:
        if self.request.method == 'POST':
            self.permission_classes = [permissions.IsAuthenticated]
        return super().get_permissions()

    def get_serializer_class(self) -> type[BaseSerializer[Any]]:
        return import_from_string(get_setting('ORGANIZATION_SERIALIZER'))

    def get_queryset(self) -> QuerySet[Organization]:
        if self.request.user.is_authenticated:
            return Organization.objects.filter(memberships__user=self.request.user).distinct()
        else:
            return Organization.objects.none()


class OrganizationDetailsView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [DjangoOrganizationModelPermissions]

    def get_serializer_class(self) -> type[BaseSerializer[Any]]:
        return import_from_string(get_setting('ORGANIZATION_SERIALIZER'))

    def get_queryset(self) -> QuerySet[Organization]:
        if self.request.user.is_authenticated:
            return Organization.objects.filter(memberships__user=self.request.user).distinct()
        else:
            return Organization.objects.none()

    def get_object(self) -> Organization:
        # The organization the request is already bound to, so the detail route
        # needs no primary key of its own.
        organization = get_current_organization()
        assert organization is not None
        return organization


class OrganizationSiteListView(generics.ListCreateAPIView):
    permission_classes = [DjangoOrganizationModelPermissions]

    def get_serializer_class(self) -> type[BaseSerializer[Any]]:
        return import_from_string(get_setting('ORGANIZATION_SITE_SERIALIZER'))

    def get_queryset(self) -> QuerySet[OrganizationSite]:
        # The serializer reads ``.site`` on every row; without this it costs one
        # query per site.
        return OrganizationSite.objects.select_related('site', 'organization')

    def get_serializer(self, *args: Any, **kwargs: Any) -> BaseSerializer[Any]:
        if self.request.method == 'POST':
            data = kwargs.get('data', {})
            data['organization'] = get_current_organization()
            kwargs['data'] = data
        return super().get_serializer(*args, **kwargs)


class OrganizationSiteDetailsView(generics.DestroyAPIView):
    permission_classes = [DjangoOrganizationModelPermissions]

    def get_serializer_class(self) -> type[BaseSerializer[Any]]:
        return import_from_string(get_setting('ORGANIZATION_SITE_SERIALIZER'))

    def get_queryset(self) -> QuerySet[OrganizationSite]:
        # The serializer reads ``.site`` on every row; without this it costs one
        # query per site.
        return OrganizationSite.objects.select_related('site', 'organization')

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        organization_site = self.get_object()
        site = organization_site.site

        with transaction.atomic():
            response = super().destroy(request, *args, **kwargs)
            site.delete()

        return response
