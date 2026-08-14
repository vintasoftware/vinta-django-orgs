from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import QuerySet
from rest_framework import generics, permissions
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from vinta_orgs.conf import get_organization_membership_model, get_organization_model
from vinta_orgs.models import AbstractOrganization, OrganizationSite
from vinta_orgs.permissions import DjangoOrganizationModelPermissions
from vinta_orgs.settings import get_setting
from vinta_orgs.state import organization_state
from vinta_orgs.utils import import_from_string

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

    def get_queryset(self) -> QuerySet[AbstractOrganization]:
        organizations = get_organization_model()._default_manager

        if self.request.user.is_authenticated:
            # ``is_active`` as well as the user: a deactivated membership is
            # kept for the audit trail and grants nothing, so the organization
            # it points at is not one this caller may still select.
            organization_ids = (
                get_organization_membership_model()
                ._default_manager.filter(
                    user_id=self.request.user.pk,
                    is_active=True,
                )
                .values('organization_id')
            )
            return organizations.filter(pk__in=organization_ids)
        else:
            return organizations.none()


class OrganizationDetailsView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [DjangoOrganizationModelPermissions]

    def get_serializer_class(self) -> type[BaseSerializer[Any]]:
        return import_from_string(get_setting('ORGANIZATION_SERIALIZER'))

    def get_queryset(self) -> QuerySet[AbstractOrganization]:
        organizations = get_organization_model()._default_manager

        if self.request.user.is_authenticated:
            # ``is_active`` as well as the user: a deactivated membership is
            # kept for the audit trail and grants nothing, so the organization
            # it points at is not one this caller may still select.
            organization_ids = (
                get_organization_membership_model()
                ._default_manager.filter(
                    user_id=self.request.user.pk,
                    is_active=True,
                )
                .values('organization_id')
            )
            return organizations.filter(pk__in=organization_ids)
        else:
            return organizations.none()

    def get_object(self) -> AbstractOrganization:
        # The organization the request is already bound to, so the detail route
        # needs no primary key of its own.
        organization = organization_state.get()
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
            data['organization'] = organization_state.get()
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
