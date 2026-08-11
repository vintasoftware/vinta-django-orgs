from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self

from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import QuerySet

from organizations.querysets import OrganizationScopedQuerySetMixin

if TYPE_CHECKING:
    from organizations_custom_data.models import OrganizationSpecificFieldDefinition


class OrganizationSpecificFieldsQueryset(OrganizationScopedQuerySetMixin, QuerySet):
    data_type_fields: dict[str, models.Field[Any, Any]] = {
        'integer': models.IntegerField(),
        'char': models.CharField(max_length=255),
        'text': models.TextField(),
        'float': models.FloatField(),
        'datetime': models.DateTimeField(),
        'date': models.DateField(),
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.table_id = kwargs.pop('table_id', getattr(kwargs.pop('table', object()), 'id', -1))
        super().__init__(*args, **kwargs)
        self.get_definitions(table_id=self.table_id)

    def _clone(self, **kwargs: Any) -> Self:
        """
        Return a copy of the current QuerySet. A lightweight alternative
        to deepcopy().
        """
        # ``QuerySet``'s per-instance bookkeeping is private and undeclared, so
        # both sides of the copy are reached through an untyped view.
        source: Any = self

        query = source.query.clone()
        if source._sticky_filter:
            query.filter_is_sticky = True

        clone: Any = self.__class__(
            model=self.model, query=query, using=source._db, hints=source._hints, table_id=self.table_id
        )
        clone._for_write = source._for_write
        clone._prefetch_related_lookups = source._prefetch_related_lookups
        clone._known_related_objects = source._known_related_objects
        clone._iterable_class = source._iterable_class
        clone._fields = source._fields
        clone.definitions = source.definitions

        clone.__dict__.update(kwargs)
        return clone

    def get_definitions(self, table_id: int = -1) -> QuerySet[OrganizationSpecificFieldDefinition]:
        from organizations_custom_data.models import OrganizationSpecificFieldDefinition, OrganizationSpecificTable

        if not hasattr(self, 'definitions'):
            if self.model.__name__ == 'OrganizationSpecificTableRow':
                self.definitions = OrganizationSpecificFieldDefinition.objects.filter(
                    table_content_type=ContentType.objects.get_for_model(OrganizationSpecificTable), table_id=table_id
                )
            else:
                self.definitions = OrganizationSpecificFieldDefinition.objects.filter(
                    table_content_type=ContentType.objects.get_for_model(self.model)
                )
        return self.definitions

    def update(self, *args: Any, **kwargs: Any) -> int:
        from organizations_custom_data.helpers.custom_tables_helpers import _get_pivot_table_class_for_data_type

        definitions = self.get_definitions()
        definitions_by_name = {d.name: d for d in definitions}

        custom_fields = {k: v for k, v in kwargs.items() if k in definitions_by_name.keys()}
        common_fields = {k: v for k, v in kwargs.items() if k not in definitions_by_name.keys()}

        # ``QuerySet.update`` reports how many rows it touched, and this used to
        # drop that on the floor and hand the caller ``None`` instead.
        updated = super().update(**common_fields)

        for field_name, field_value in custom_fields.items():
            PivotTableClass = _get_pivot_table_class_for_data_type(definitions_by_name[field_name].data_type)
            (
                PivotTableClass.objects.filter(definition__id=definitions_by_name[field_name].id).update(
                    value=field_value
                )
            )

        return updated
