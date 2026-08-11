from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction

from organizations.helpers.organizations import get_current_organization
from organizations_custom_data.helpers.custom_tables_helpers import _get_pivot_table_class_for_data_type
from organizations_custom_data.managers import OrganizationSpecificFieldsModelManager

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from organizations_custom_data.models import OrganizationSpecificFieldDefinition


class OrganizationSpecificFieldsModelMixin(models.Model):
    objects = OrganizationSpecificFieldsModelManager()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        table_id = kwargs.get('table_id', getattr(kwargs.get('table'), 'id', None))
        definitions = self.get_definitions(table_id=table_id)
        for definition in definitions:
            if definition.name in kwargs.keys():
                setattr(self, definition.name, kwargs.pop(definition.name))
        super().__init__(*args, **kwargs)

    def get_definitions(
        self, table_id: int | None = -1, force_hit_db: bool = False
    ) -> QuerySet[OrganizationSpecificFieldDefinition]:
        from organizations_custom_data.models import OrganizationSpecificFieldDefinition, OrganizationSpecificTable

        if not hasattr(self, 'definitions') or force_hit_db:
            if type(self).__name__ == 'OrganizationSpecificTableRow':
                self.definitions = OrganizationSpecificFieldDefinition.objects.filter(
                    table_content_type=ContentType.objects.get_for_model(OrganizationSpecificTable), table_id=table_id
                )
            else:
                self.definitions = OrganizationSpecificFieldDefinition.objects.filter(
                    table_content_type=ContentType.objects.get_for_model(type(self))
                )
        return self.definitions

    def create_organization_specific_fields(self, organization_specific_fields_data: dict[str, Any]) -> None:
        definitions = self.get_definitions()
        definitions_by_name = {d.name: d for d in definitions}

        with transaction.atomic():
            for field_name, definition in definitions_by_name.items():
                field_value = organization_specific_fields_data.get(field_name, getattr(self, field_name, None))
                PivotTableClass = _get_pivot_table_class_for_data_type(definition.data_type)
                PivotTableClass.objects.create(
                    definition=definition,
                    row_id=self.pk,
                    row_content_type=ContentType.objects.get_for_model(self.__class__),
                    value=field_value,
                )

    def update_organization_specific_fields(self, organization_specific_fields_data: dict[str, Any]) -> None:
        old = self.__class__.objects.get(pk=self.pk)
        definitions = self.get_definitions()
        definitions_by_name = {d.name: d for d in definitions}

        with transaction.atomic():
            for field_name, definition in definitions_by_name.items():
                new_value = organization_specific_fields_data.get(field_name, None)
                old_value = getattr(old, field_name, None)
                PivotTableClass = _get_pivot_table_class_for_data_type(definition.data_type)
                if new_value != old_value:
                    PivotTableClass.objects.filter(
                        definition__id=definition.id,
                        row_id=self.pk,
                        row_content_type=ContentType.objects.get_for_model(self.__class__),
                    ).update(value=new_value)

    def save(self, *args: Any, **kwargs: Any) -> None:
        table_id = getattr(self, 'table_id', getattr(getattr(self, 'table', object()), 'id', None))

        force_hit_db = False
        if hasattr(self, 'definitions') and not self.definitions.exists():
            force_hit_db = True

        definitions = self.get_definitions(table_id=table_id, force_hit_db=force_hit_db)
        organization_specific_fields_data: dict[str, Any] = {}
        for definition in definitions:
            if hasattr(self, definition.name):
                organization_specific_fields_data[definition.name] = getattr(self, definition.name)
                delattr(self, definition.name)
            else:
                organization_specific_fields_data[definition.name] = definition.default_value

        if not self.pk:
            # ``setattr`` to match the ``hasattr``: the field belongs to
            # ``SingleOrganizationModelMixin``, which subclasses mix in
            # alongside this one, so this class cannot declare it.
            organization_field = 'organization'
            if not hasattr(self, organization_field):
                setattr(self, organization_field, get_current_organization())
            super().save(*args, **kwargs)
            self.create_organization_specific_fields(organization_specific_fields_data)
        else:
            super().save(*args, **kwargs)
            self.update_organization_specific_fields(organization_specific_fields_data)

        self.organization_specific_fields_data: dict[str, Any] = {}

    @property
    def fields_definitions(self) -> QuerySet[OrganizationSpecificFieldDefinition]:
        return self.get_definitions()

    class Meta:
        abstract = True


class OrganizationSpecificPivotTable(models.Model):
    """One row per (definition, target row) pair, holding a single value.

    Concrete subclasses add the ``value`` column -- one per data type, since
    that is what a pivot table is for -- and the organization scoping.
    """

    if TYPE_CHECKING:
        #: Contributed by each concrete subclass as the field type it stores,
        #: which is what tells the six subclasses apart.
        value: Any

    # App-qualified rather than a bare model name: this abstract base does not
    # live in ``models.py``, so nothing but the label says which app the target
    # belongs to.
    definition = models.ForeignKey(
        'organizations_custom_data.OrganizationSpecificFieldDefinition', on_delete=models.CASCADE
    )

    row_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    row_id = models.PositiveIntegerField()
    row = GenericForeignKey(ct_field='row_content_type', fk_field='row_id')

    def __str__(self) -> str:
        return '%s: %s' % (str(self.definition), self.value)

    class Meta:
        unique_together = [('definition', 'row_id', 'row_content_type')]
        abstract = True
