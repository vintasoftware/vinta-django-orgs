from django.contrib.contenttypes.models import ContentType
from model_bakery import baker

from organizations_custom_data.helpers.custom_tables_helpers import (
    _get_pivot_table_class_for_data_type,
    get_custom_table_manager,
)
from organizations_custom_data.models import (
    OrganizationSpecificFieldDefinition,
    OrganizationSpecificTable,
    OrganizationSpecificTableRow,
)
from tests.utils import OrganizationsTestCase


class OrganizationSpecificTableTests(OrganizationsTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.table = baker.make(OrganizationSpecificTable, organization=self.organization)
        self.fields = baker.make(
            OrganizationSpecificFieldDefinition,
            table_id=self.table.id,
            table_content_type=ContentType.objects.get_for_model(OrganizationSpecificTable),
            data_type=OrganizationSpecificFieldDefinition.DATA_TYPES.integer,
            default_value='1',
            organization=self.organization,
            _quantity=10,
        )

        self.row = baker.make(OrganizationSpecificTableRow, table=self.table, organization=self.organization)

        for i, field in enumerate(self.fields):
            PivotTableClass = _get_pivot_table_class_for_data_type(field.data_type)
            PivotTableClass.objects.filter(row_id=self.row.id, definition=field).update(value=i + 5)

    def test_can_filter_by_organization_specific_fields(self) -> None:
        row = get_custom_table_manager(self.table.name).all().first()

        for i, field in enumerate(self.fields):
            self.assertEqual(getattr(row, field.name, None), i + 5)

    def test_filter_by_organization_specific_field(self) -> None:
        for i, field in enumerate(self.fields):
            rows = get_custom_table_manager(self.table.name).filter(**{field.name: i + 5})
            self.assertEqual(rows.count(), 1)

    def test_exclude_by_organization_specific_field(self) -> None:
        for i, field in enumerate(self.fields):
            rows = get_custom_table_manager(self.table.name).exclude(**{field.name: i + 5})
            self.assertEqual(rows.count(), 0)

    def test_filter_by_organization_specific_field_with_lookup(self) -> None:
        for i, field in enumerate(self.fields):
            rows = get_custom_table_manager(self.table.name).filter(**{field.name + '__gte': i})
            self.assertEqual(rows.count(), 1)

    def test_create_row_with_specific_fields_values(self) -> None:
        field_value_dict = {}
        for i, field in enumerate(self.fields):
            field_value_dict[field.name] = i + 50

        get_custom_table_manager(self.table.name).create(**field_value_dict)

        for i, field in enumerate(self.fields):
            rows = get_custom_table_manager(self.table.name).filter(**{field.name: i + 50})
            self.assertEqual(rows.count(), 1)

        self.assertEqual(get_custom_table_manager(self.table.name).all().count(), 2)

    def test_update_row_with_specific_fields_values(self) -> None:
        field_value_dict = {}
        for i, field in enumerate(self.fields):
            field_value_dict[field.name] = i + 50

        (
            get_custom_table_manager(self.table.name)
            .filter(table_id=self.table.id, id=self.row.id)
            .update(**field_value_dict)
        )

        for i, field in enumerate(self.fields):
            rows = get_custom_table_manager(self.table.name).filter(**{field.name: i + 50})
            self.assertEqual(rows.count(), 1)

        self.assertEqual(get_custom_table_manager(self.table.name).all().count(), 1)
