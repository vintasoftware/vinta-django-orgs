from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import QuerySet
from django.db.models.expressions import Combinable
from django.db.models.manager import BaseManager
from django.utils.version import get_complete_version

from vinta_orgs.managers import SingleOrganizationModelManager
from vinta_orgs_custom_data.helpers.custom_tables_helpers import _get_pivot_table_class_for_data_type
from vinta_orgs_custom_data.querysets import OrganizationSpecificFieldsQueryset

if TYPE_CHECKING:
    from vinta_orgs_custom_data.models import OrganizationSpecificFieldDefinition


class OrganizationSpecificFieldsModelBaseManager(BaseManager):
    @classmethod
    def _get_queryset_methods(cls, queryset_class: type[QuerySet[Any]]) -> dict[str, Callable[..., Any]]:
        import inspect

        def create_method(name: str, method: Callable[..., Any]) -> Callable[..., Any]:
            def manager_method(self: Any, *args: Any, **kwargs: Any) -> Any:
                if self.model.__name__ == 'OrganizationSpecificTableRow':
                    table_id = getattr(self, 'table_id', None)
                    kwargs['table_id'] = table_id
                    return getattr(self.get_queryset(table_id=table_id), name)(*args, **kwargs)
                return getattr(self.get_queryset(), name)(*args, **kwargs)

            manager_method.__name__ = method.__name__
            manager_method.__doc__ = method.__doc__
            return manager_method

        new_methods: dict[str, Callable[..., Any]] = {}
        for name, method in inspect.getmembers(queryset_class, predicate=inspect.isfunction):
            # Only copy missing methods.
            if hasattr(cls, name):
                continue
            # Only copy public methods or methods with the attribute `queryset_only=False`.
            queryset_only = getattr(method, 'queryset_only', None)
            if queryset_only or (queryset_only is None and name.startswith('_')):
                continue
            # Copy the method onto the manager.
            new_methods[name] = create_method(name, method)
        return new_methods


# ``from_queryset`` builds its class at runtime. Spelling out what it produces
# -- the manager plus the queryset methods the manager does not already have --
# keeps those methods checked instead of degrading the whole class to ``Any``.
if TYPE_CHECKING:

    class _OrganizationSpecificFieldsManagerBase(OrganizationSpecificFieldsModelBaseManager, models.Manager[Any]):
        # ``Manager`` is itself ``BaseManager.from_queryset(QuerySet)``, so
        # listing it as a base is what gives this one ``get``, ``filter`` and
        # the rest. Only the methods beyond a plain queryset's are spelled out.
        #
        # ``for_current_organization`` is deliberately left out: it comes from
        # ``OrganizationScopedQuerySetMixin`` on both this queryset and
        # ``SingleOrganizationQuerySet``, which the row manager combines, and
        # the two return sibling queryset classes that nothing reconciles.
        def get_definitions(self, table_id: int = -1) -> QuerySet[OrganizationSpecificFieldDefinition]: ...
else:
    _OrganizationSpecificFieldsManagerBase = OrganizationSpecificFieldsModelBaseManager.from_queryset(
        OrganizationSpecificFieldsQueryset
    )


class OrganizationSpecificFieldsModelManager(_OrganizationSpecificFieldsManagerBase):
    data_type_fields: dict[str, models.Field[Any, Any]] = {
        'integer': models.IntegerField(),
        'char': models.CharField(max_length=255),
        'text': models.TextField(),
        'float': models.FloatField(),
        'datetime': models.DateTimeField(),
        'date': models.DateField(),
    }

    def get_queryset(self, *args: Any, **kwargs: Any) -> QuerySet[Any]:
        from vinta_orgs_custom_data.models import OrganizationSpecificTableRow

        if self.model != OrganizationSpecificTableRow:
            kwargs.pop('table_id', None)
        else:
            if not hasattr(self, 'table_id'):
                self.table_id = kwargs.get('table_id', -1)
            else:
                kwargs['table_id'] = self.table_id

        custom_fields_annotations = self._get_custom_fields_annotations()
        queryset = super().get_queryset(*args, **kwargs)

        if len(custom_fields_annotations.keys()) > 0:
            if self.model == OrganizationSpecificTableRow:
                return queryset.annotate(**custom_fields_annotations).filter(table_id=self.table_id)
            return queryset.annotate(**custom_fields_annotations)

        if self.model == OrganizationSpecificTableRow:
            return queryset.filter(table_id=self.table_id)
        return queryset

    def _get_custom_fields_annotations(self) -> dict[str, Combinable]:
        from vinta_orgs_custom_data.models import (
            OrganizationSpecificFieldDefinition,
            OrganizationSpecificTable,
            OrganizationSpecificTableRow,
        )

        if self.model == OrganizationSpecificTableRow:
            definitions = OrganizationSpecificFieldDefinition.objects.filter(
                table_content_type=ContentType.objects.get_for_model(OrganizationSpecificTable), table_id=self.table_id
            )
        else:
            definitions = OrganizationSpecificFieldDefinition.objects.filter(
                table_content_type=ContentType.objects.get_for_model(self.model)
            )
        definitions_by_name = {d.name: d for d in definitions}

        custom_fields_annotations: dict[str, Combinable] = {}

        for key, definition in definitions_by_name.items():
            if get_complete_version()[1] >= 11:
                from django.db.models import OuterRef, Subquery

                definitions_values = (
                    _get_pivot_table_class_for_data_type(definition.data_type)
                    .objects.filter(definition__id=definition.id, row_id=OuterRef('pk'))
                    .values('value')
                )

                custom_fields_annotations[key] = Subquery(
                    queryset=definitions_values, output_field=self.data_type_fields[definition.data_type]
                )
            else:
                from django.db.models.expressions import RawSQL

                model_content_type = ContentType.objects.get_for_model(self.model)
                model_table_name = model_content_type.app_label + '_' + model_content_type.model
                PivotTableClass = _get_pivot_table_class_for_data_type(definition.data_type)
                pivot_table_name = PivotTableClass._meta.db_table
                custom_fields_annotations[key] = RawSQL(
                    """
                        select p.value
                        from """
                    + pivot_table_name
                    + """ p
                        where definition_id = %s and
                            p.row_id = """
                    + '"'
                    + model_table_name
                    + '"."'
                    + self.model._meta.pk.name
                    + '"',
                    [definition.id],
                    output_field=self.data_type_fields[definition.data_type],
                )

        return custom_fields_annotations


class ManagerPassesTableIdToQueryset(models.Manager):
    #: Declared, never assigned here: ``get_custom_table_manager`` sets it on
    #: the instance, and ``OrganizationSpecificFieldsModelManager.get_queryset``
    #: keys off whether it has been set yet. A class-level default would make
    #: that ``hasattr`` check always true.
    table_id: int

    def get_queryset(self, table_id: int = -1) -> QuerySet[Any]:
        # ``_queryset_class`` and ``_hints`` are ``Manager`` internals, which
        # the type stubs do not declare.
        manager: Any = self
        return manager._queryset_class(model=self.model, using=self._db, hints=manager._hints, table_id=self.table_id)


class OrganizationSpecificTableRowManager(
    OrganizationSpecificFieldsModelManager, SingleOrganizationModelManager, ManagerPassesTableIdToQueryset
):
    pass
