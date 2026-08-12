from typing import Any

from django.contrib.contenttypes.models import ContentType
from model_bakery import baker

from exampleproject.lectures.forms import LectureForm
from exampleproject.lectures.models import Lecture
from tests.utils import OrganizationsAPITestCase
from vinta_orgs.helpers.organizations import set_current_organization
from vinta_orgs_custom_data.forms import get_organization_specific_table_row_form_class
from vinta_orgs_custom_data.helpers.custom_tables_helpers import (
    _get_pivot_table_class_for_data_type,
    get_custom_table_manager,
)
from vinta_orgs_custom_data.models import (
    OrganizationSpecificFieldDefinition,
    OrganizationSpecificFieldsValidator,
    OrganizationSpecificTable,
    OrganizationSpecificTableRow,
)


class OrganizationSpecificTableRowFormTests(OrganizationsAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.table = baker.make(OrganizationSpecificTable, organization=self.organization)
        self.validator_gt_2 = baker.make(
            OrganizationSpecificFieldsValidator,
            module_path='vinta_orgs_custom_data.tests.validators.validator_gt_2',
        )
        self.fields = baker.make(
            OrganizationSpecificFieldDefinition,
            table_id=self.table.id,
            table_content_type=ContentType.objects.get_for_model(OrganizationSpecificTable),
            data_type=OrganizationSpecificFieldDefinition.DATA_TYPES.integer,
            default_value='1',
            organization=self.organization,
            validators=[self.validator_gt_2],
            _quantity=10,
        )

        self.row = baker.make(OrganizationSpecificTableRow, table=self.table, organization=self.organization)

        for i, field in enumerate(self.fields):
            PivotTableClass = _get_pivot_table_class_for_data_type(field.data_type)
            PivotTableClass.objects.filter(row_id=self.row.id, definition=field).update(value=i + 5)

        self.params = {field.name: i + 1000 for i, field in enumerate(self.fields)}
        set_current_organization(self.organization.slug)

    def test_create(self) -> None:
        form = get_organization_specific_table_row_form_class(self.table.name)(data=self.params)
        self.assertTrue(form.is_valid())

        instance = form.save()

        self.assertEqual(get_custom_table_manager(self.table.name).all().count(), 2)

        for key, value in self.params.items():
            self.assertEqual(getattr(instance, key), value)

    def test_create_invalid(self) -> None:
        self.params[self.fields[0].name] = -100
        form = get_organization_specific_table_row_form_class(self.table.name)(data=self.params)
        self.assertFalse(form.is_valid())

    def test_update(self) -> None:
        form = get_organization_specific_table_row_form_class(self.table.name)(instance=self.row, data=self.params)
        self.assertTrue(form.is_valid())
        form.save()
        updated_row = get_custom_table_manager(self.table.name).get(id=self.row.id)
        for key, value in self.params.items():
            self.assertEqual(getattr(updated_row, key), value)


class LectureFormTests(OrganizationsAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.validator_gt_2 = baker.make(
            OrganizationSpecificFieldsValidator,
            module_path='vinta_orgs_custom_data.tests.validators.validator_gt_2',
        )
        self.lecture_fields = baker.make(
            OrganizationSpecificFieldDefinition,
            table_content_type=ContentType.objects.get_for_model(Lecture),
            data_type=OrganizationSpecificFieldDefinition.DATA_TYPES.integer,
            default_value='1',
            organization=self.organization,
            validators=[self.validator_gt_2],
            _quantity=2,
        )

        lecture_fields_values: dict[str, Any] = {lf.name: i + 100 for i, lf in enumerate(self.lecture_fields)}
        self.lecture = baker.make(Lecture, **lecture_fields_values)

        self.params: dict[str, Any] = {
            'subject': 'Test',
            'description': (
                'Lorem ipsum dolor sit amet consectetur adipisicing elit. '
                'Recusandae, qui? Voluptate reprehenderit vel mollitia, '
                'placeat et aperiam sit voluptatibus eum deserunt corrupti '
                'nulla quidem nesciunt atque dicta, accusantium ipsam at?'
            ),
            'speaker': self.user.id,
        }
        self.params.update({field.name: i + 1000 for i, field in enumerate(self.lecture_fields)})
        set_current_organization(self.organization.slug)

    def test_create(self) -> None:
        form = LectureForm(data=self.params)
        self.assertTrue(form.is_valid())

        instance = form.save()

        self.assertEqual(Lecture.objects.all().count(), 2)

        for key, value in self.params.items():
            if key != 'speaker':
                self.assertEqual(getattr(instance, key), value)
            else:
                self.assertEqual(getattr(instance, key).pk, value)

    def test_create_invalid(self) -> None:
        self.params[self.lecture_fields[0].name] = -100
        form = LectureForm(data=self.params)
        self.assertFalse(form.is_valid())

    def test_update(self) -> None:
        form = LectureForm(instance=self.lecture, data=self.params)
        self.assertTrue(form.is_valid())
        form.save()
        updated_lecture = Lecture.objects.get(id=self.lecture.id)
        for key, value in self.params.items():
            if key != 'speaker':
                self.assertEqual(getattr(updated_lecture, key), value)
            else:
                self.assertEqual(getattr(updated_lecture, key).pk, value)
