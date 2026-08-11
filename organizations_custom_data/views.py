from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import QuerySet
from django.http import Http404
from rest_framework import generics, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.views import APIView

from organizations.utils import import_from_string
from organizations_custom_data.helpers.custom_tables_helpers import get_custom_table_manager
from organizations_custom_data.models import OrganizationSpecificFieldDefinition, OrganizationSpecificTable
from organizations_custom_data.permissions import DjangoOrganizationSpecificTablePermissions
from organizations_custom_data.serializers import (
    OrganizationSpecificFieldsModelDefinitionsUpdateSerializer,
    OrganizationSpecificTableSerializer,
    get_organization_specific_table_row_serializer_class,
)
from organizations_custom_data.settings import get_setting

if TYPE_CHECKING:
    # The protocol DRF's own ``get_permissions`` is declared to return; it
    # exists only in the type stubs.
    from rest_framework.permissions import _SupportsHasPermission


class CustomizableModelsList(APIView):
    def get_permissions(self) -> Sequence[_SupportsHasPermission]:
        return [
            import_from_string(permission)()
            for permission in get_setting('CUSTOMIZABLE_MODELS_LIST_CREATE_PERMISSIONS')
        ]

    def get_queryset(self) -> dict[str, Any]:
        custom_tables = OrganizationSpecificTable.objects.all()
        customizable_models_names = get_setting('CUSTOMIZABLE_MODELS')

        search = self.request.GET.get('search')
        if search:
            custom_tables = custom_tables.filter(name__icontains=search)
            customizable_models_names = [
                m.replace('.', get_setting('CUSTOMIZABLE_TABLES_LABEL_SEPARATOR')).lower()
                for m in customizable_models_names
                if search in m.replace('.', get_setting('CUSTOMIZABLE_TABLES_LABEL_SEPARATOR')).lower()
            ]

        filter_results = self.request.GET.get('filter')
        if filter_results == get_setting('CUSTOM_TABLES_FILTER_KEYWORD'):
            customizable_models_names = []
        elif filter_results == 'customizable_models':
            custom_tables = custom_tables.none()

        return {
            'custom_tables': custom_tables.order_by('name'),
            'customizable_models_names': sorted(customizable_models_names),
        }

    def get_custom_tables_names(self, custom_tables: QuerySet[OrganizationSpecificTable]) -> list[str]:
        return [
            get_setting('CUSTOM_TABLES_LABEL') + get_setting('CUSTOMIZABLE_TABLES_LABEL_SEPARATOR') + t
            for t in custom_tables.values_list('name', flat=True)
        ]

    def paginate_results(
        self, custom_tables: QuerySet[OrganizationSpecificTable], customizable_models_names: list[str]
    ) -> list[dict[str, str]] | dict[str, Any]:
        raw_page_number = self.request.GET.get('page')
        raw_page_length = self.request.GET.get('length')
        total_count = len(customizable_models_names + self.get_custom_tables_names(custom_tables))

        if not raw_page_number or not raw_page_length:
            return [{'name': n} for n in (customizable_models_names + self.get_custom_tables_names(custom_tables))]

        page_number = int(raw_page_number)
        page_length = int(raw_page_length)
        first_item_index = (page_number - 1) * page_length
        last_item_index = first_item_index + page_length
        if len(customizable_models_names) > last_item_index:
            return {
                'count': total_count,
                'results': [{'name': n} for n in (customizable_models_names[first_item_index:last_item_index])],
            }

        if len(customizable_models_names) >= first_item_index:
            selected_customizable_models_names = customizable_models_names[first_item_index:]
            return {
                'count': total_count,
                'results': [
                    {'name': n}
                    for n in (
                        selected_customizable_models_names
                        + self.get_custom_tables_names(
                            custom_tables[0 : page_length - len(selected_customizable_models_names)]
                        )
                    )
                ],
            }

        return {
            'count': total_count,
            'results': [
                {'name': n} for n in (self.get_custom_tables_names(custom_tables[first_item_index:last_item_index]))
            ],
        }

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(self.paginate_results(**self.get_queryset()))

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = OrganizationSpecificTableSerializer(
            data=self.request.data, context={'request': request, 'view': self}
        )

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CustomTableDetails(generics.RetrieveUpdateDestroyAPIView):
    def get_permissions(self) -> Sequence[_SupportsHasPermission]:
        return [
            import_from_string(permission)()
            for permission in get_setting('CUSTOMIZABLE_MODELS_RETRIEVE_UTPADE_DESTROY_PERMISSIONS')
        ]

    def get_queryset(self) -> QuerySet[Any]:
        table_slug = self.kwargs['slug']
        table_slug_parts = table_slug.split(get_setting('CUSTOMIZABLE_TABLES_LABEL_SEPARATOR'))
        app = table_slug_parts[0]

        if app == get_setting('CUSTOM_TABLES_LABEL'):
            return OrganizationSpecificTable.objects.all()

        return ContentType.objects.filter()

    def get_object(self) -> Any:
        if not hasattr(self, 'object'):
            table_slug = self.kwargs['slug']
            table_slug_parts = table_slug.split(get_setting('CUSTOMIZABLE_TABLES_LABEL_SEPARATOR'))
            app = table_slug_parts[0]

            try:
                if app == get_setting('CUSTOM_TABLES_LABEL'):
                    self.object = self.get_queryset().get(name=table_slug_parts[1])
                elif table_slug in [
                    m.replace('.', get_setting('CUSTOMIZABLE_TABLES_LABEL_SEPARATOR')).lower()
                    for m in get_setting('CUSTOMIZABLE_MODELS')
                ]:
                    self.object = ContentType.objects.get_by_natural_key(*table_slug_parts)
                else:
                    raise Http404()
            except ObjectDoesNotExist as exc:
                raise Http404() from exc
        return self.object

    def get_serializer_class(self) -> type[BaseSerializer[Any]]:
        obj = self.get_object()
        if type(obj).__name__ == 'OrganizationSpecificTable':
            return OrganizationSpecificTableSerializer

        return OrganizationSpecificFieldsModelDefinitionsUpdateSerializer

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        obj = self.get_object()

        if type(obj).__name__ == 'OrganizationSpecificTable':
            OrganizationSpecificFieldDefinition.objects.filter(
                table_content_type=ContentType.objects.get_for_model(OrganizationSpecificTable), table_id=obj.id
            ).delete()
            obj.delete()
        else:
            OrganizationSpecificFieldDefinition.objects.filter(table_content_type=obj).delete()

        return Response()


class OrganizationSpecificTableRowViewset(viewsets.ModelViewSet):
    permission_classes = [DjangoOrganizationSpecificTablePermissions]

    def get_queryset(self) -> QuerySet[Any]:
        table_slug = self.kwargs['slug']
        if get_setting('CUSTOMIZABLE_TABLES_LABEL_SEPARATOR') in table_slug:
            table_slug_parts = table_slug.split(get_setting('CUSTOMIZABLE_TABLES_LABEL_SEPARATOR'))
            if table_slug_parts[0] == get_setting('CUSTOM_TABLES_LABEL'):
                try:
                    return get_custom_table_manager(table_slug_parts[1]).all()
                except OrganizationSpecificTable.DoesNotExist:
                    pass

        raise Http404()

    def get_serializer_class(self) -> type[BaseSerializer[Any]]:
        table_slug = self.kwargs['slug']
        if get_setting('CUSTOMIZABLE_TABLES_LABEL_SEPARATOR') in table_slug:
            table_slug_parts = table_slug.split(get_setting('CUSTOMIZABLE_TABLES_LABEL_SEPARATOR'))
            if table_slug_parts[0] == get_setting('CUSTOM_TABLES_LABEL'):
                try:
                    return get_organization_specific_table_row_serializer_class(table_slug_parts[1])
                except OrganizationSpecificTable.DoesNotExist:
                    pass

        raise Http404()
