from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from organizations_custom_data.managers import OrganizationSpecificTableRowManager


def get_custom_table_manager(table_name: str) -> OrganizationSpecificTableRowManager:
    from organizations_custom_data.managers import OrganizationSpecificTableRowManager
    from organizations_custom_data.models import OrganizationSpecificTable, OrganizationSpecificTableRow

    table = OrganizationSpecificTable.objects.get(name=table_name)
    manager: OrganizationSpecificTableRowManager = OrganizationSpecificTableRowManager()
    manager.model = OrganizationSpecificTableRow
    manager.table_id = table.id
    return manager


def _get_pivot_table_class_for_data_type(data_type: str) -> Any:
    """The concrete pivot table storing values of ``data_type``.

    ``data_type`` comes from ``OrganizationSpecificFieldDefinition``, whose
    ``StatusField`` only accepts the six names below. An unknown one used to
    fall off the end and return ``None``, which surfaced as an ``AttributeError``
    on ``None`` at whichever call site went on to use the result.

    The return type is ``Any`` rather than
    ``type[OrganizationSpecificPivotTable]``: the six classes differ in exactly
    the thing callers reach for -- the type of ``value`` -- and they take their
    manager from ``SingleOrganizationModelMixin``, which the abstract pivot base
    knows nothing about.
    """
    from organizations_custom_data.models import (
        OrganizationSpecificFieldCharPivot,
        OrganizationSpecificFieldDatePivot,
        OrganizationSpecificFieldDateTimePivot,
        OrganizationSpecificFieldFloatPivot,
        OrganizationSpecificFieldIntegerPivot,
        OrganizationSpecificFieldTextPivot,
    )

    if data_type == 'integer':
        return OrganizationSpecificFieldIntegerPivot
    elif data_type == 'char':
        return OrganizationSpecificFieldCharPivot
    elif data_type == 'text':
        return OrganizationSpecificFieldTextPivot
    elif data_type == 'float':
        return OrganizationSpecificFieldFloatPivot
    elif data_type == 'date':
        return OrganizationSpecificFieldDatePivot
    elif data_type == 'datetime':
        return OrganizationSpecificFieldDateTimePivot

    raise ValueError('%r is not a supported organization specific field data type' % data_type)
