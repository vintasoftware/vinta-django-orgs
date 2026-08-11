from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from django import forms
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.forms.fields import FileField

from organizations.utils import import_from_string
from organizations_custom_data.helpers.custom_tables_helpers import get_custom_table_manager
from organizations_custom_data.models import (
    OrganizationSpecificFieldDefinition,
    OrganizationSpecificTable,
    OrganizationSpecificTableRow,
)
from organizations_custom_data.utils import compose_list

if TYPE_CHECKING:

    class _ModelFormBase(forms.ModelForm):
        """The parts of ``BaseForm``/``BaseModelForm`` the forms below build on.

        Django implements every one of these; django-stubs declares none of
        them, so they are named here rather than silenced at each call site.
        Nothing is added at runtime.
        """

        #: Supplied by each concrete subclass.
        Meta: ClassVar[type[Any]]

        def _clean_fields(self) -> None: ...
        def _clean_form(self) -> None: ...
        def _post_clean(self) -> None: ...
else:
    _ModelFormBase = forms.ModelForm


class OrganizationSpecificModelForm(_ModelFormBase):
    form_organization_specific_field_mapping: dict[str, type[forms.Field]] = {
        'integer': forms.IntegerField,
        'char': forms.CharField,
        'text': forms.CharField,
        'float': forms.FloatField,
        'datetime': forms.DateTimeField,
        'date': forms.DateField,
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        ModelClass = self.Meta.model

        self.organization_specific_fields_definitions = OrganizationSpecificFieldDefinition.objects.filter(
            table_content_type=ContentType.objects.get_for_model(ModelClass)
        )
        self.organization_specific_fields_names = list(
            self.organization_specific_fields_definitions.values_list('name', flat=True)
        )

        super().__init__(*args, **kwargs)

        for definition in self.organization_specific_fields_definitions:
            if not self.fields.get(definition.name, False):
                field_kwargs: dict[str, Any] = {}
                if definition.is_required:
                    field_kwargs.update({'required': True, 'allow_null': True})
                if definition.default_value is not None:
                    field_kwargs.update({'initial': definition.default_value})

                self.fields[definition.name] = self.form_organization_specific_field_mapping[definition.data_type](
                    **field_kwargs
                )

    def full_clean(self) -> None:
        """
        Clean all of self.data and populate self._errors and self.cleaned_data.
        """
        from django.forms.utils import ErrorDict

        self._errors = ErrorDict()
        if not self.is_bound:  # Stop further processing.
            return
        self.cleaned_data = {}
        # If the form is permitted to be empty, and none of the form data has
        # changed from the initial data, short circuit any validation.
        if self.empty_permitted and not self.has_changed():
            return

        self._clean_fields()
        self._clean_organization_specific_fields()
        self._clean_form()
        self._post_clean()

    def _clean_organization_specific_fields(self) -> None:
        organization_specific_fields_names = self.organization_specific_fields_definitions.values_list(
            'name', flat=True
        )
        for name, field in self.fields.items():
            if name in organization_specific_fields_names:
                definition = self.organization_specific_fields_definitions.get(name=name)
                value = field.widget.value_from_datadict(self.data, self.files, self.add_prefix(name))
                try:
                    value = field.clean(value)
                    validators = []
                    for validator_instance in definition.validators.all():
                        validator_function = import_from_string(validator_instance.module_path)
                        validators.append(validator_function)

                    validate_method = compose_list(validators)
                    self.cleaned_data[name] = validate_method(value)
                    if hasattr(self, 'clean_%s' % name):
                        value = getattr(self, 'clean_%s' % name)()
                        self.cleaned_data[name] = value
                except ValidationError as e:
                    self.add_error(name, e)

    def _clean_fields(self) -> None:
        organization_specific_fields_names = self.organization_specific_fields_definitions.values_list(
            'name', flat=True
        )
        for name, field in self.fields.items():
            # value_from_datadict() gets the data from the data dictionaries.
            # Each widget type knows how to retrieve its own data, because some
            # widgets split data over several HTML fields.
            if name not in organization_specific_fields_names:
                if field.disabled:
                    value = self.get_initial_for_field(field, name)
                else:
                    value = field.widget.value_from_datadict(self.data, self.files, self.add_prefix(name))
                try:
                    if isinstance(field, FileField):
                        initial = self.get_initial_for_field(field, name)
                        value = field.clean(value, initial)
                    else:
                        value = field.clean(value)
                    self.cleaned_data[name] = value
                    if hasattr(self, 'clean_%s' % name):
                        value = getattr(self, 'clean_%s' % name)()
                        self.cleaned_data[name] = value
                except ValidationError as e:
                    self.add_error(name, e)

    def _post_clean(self) -> None:
        super()._post_clean()
        for name, value in [
            (k, v) for k, v in self.cleaned_data.items() if k in self.organization_specific_fields_names
        ]:
            setattr(self.instance, name, value)

    def save(self, *args: Any, **kwargs: Any) -> Any:
        # Re-read through the model's own manager so the saved row comes back
        # with its organization specific fields annotated.
        ModelClass: Any = self.Meta.model
        new_instance = super().save(*args, **kwargs)
        return ModelClass.objects.get(id=new_instance.id)


def get_organization_specific_table_row_form_class(table_name: str) -> type[forms.ModelForm]:

    table_id = OrganizationSpecificTable.objects.get(name=table_name).id
    organization_specific_fields_definitions = OrganizationSpecificFieldDefinition.objects.filter(
        table_content_type=ContentType.objects.get_for_model(OrganizationSpecificTable), table_id=table_id
    )
    organization_specific_fields_names = list(organization_specific_fields_definitions.values_list('name', flat=True))

    class OrganizationSpecificTableRowForm(_ModelFormBase):
        class Meta:
            model = OrganizationSpecificTableRow
            fields = ['id']

        form_organization_specific_field_mapping: dict[str, type[forms.Field]] = {
            'integer': forms.IntegerField,
            'char': forms.CharField,
            'text': forms.CharField,
            'float': forms.FloatField,
            'datetime': forms.DateTimeField,
            'date': forms.DateField,
        }

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)

            for definition in organization_specific_fields_definitions:
                if not self.fields.get(definition.name, False):
                    field_kwargs: dict[str, Any] = {}
                    if definition.is_required:
                        field_kwargs.update({'required': True, 'allow_null': True})
                    if definition.default_value is not None:
                        field_kwargs.update({'initial': definition.default_value})

                    self.fields[definition.name] = self.form_organization_specific_field_mapping[definition.data_type](
                        **field_kwargs
                    )

        def full_clean(self) -> None:
            """
            Clean all of self.data and populate self._errors and self.cleaned_data.
            """
            from django.forms.utils import ErrorDict

            self._errors = ErrorDict()
            if not self.is_bound:  # Stop further processing.
                return
            self.cleaned_data = {'table_id': table_id}
            # If the form is permitted to be empty, and none of the form data has
            # changed from the initial data, short circuit any validation.
            if self.empty_permitted and not self.has_changed():
                return

            self._clean_fields()
            self._clean_organization_specific_fields()
            self._clean_form()
            self._post_clean()

        def _clean_organization_specific_fields(self) -> None:
            for name, field in self.fields.items():
                if name in organization_specific_fields_names:
                    definition = organization_specific_fields_definitions.get(name=name)
                    value = field.widget.value_from_datadict(self.data, self.files, self.add_prefix(name))
                    try:
                        value = field.clean(value)
                        validators = []
                        for validator_instance in definition.validators.all():
                            validator_function = import_from_string(validator_instance.module_path)
                            validators.append(validator_function)

                        validate_method = compose_list(validators)
                        self.cleaned_data[name] = validate_method(value)
                        if hasattr(self, 'clean_%s' % name):
                            value = getattr(self, 'clean_%s' % name)()
                            self.cleaned_data[name] = value
                    except ValidationError as e:
                        self.add_error(name, e)

        def save(self, *args: Any, **kwargs: Any) -> OrganizationSpecificTableRow:
            self.instance.table_id = table_id
            new_instance = super().save(*args, **kwargs)
            return get_custom_table_manager(table_name).get(id=new_instance.id)

        def _post_clean(self) -> None:
            super()._post_clean()
            for name, value in [
                (k, v) for k, v in self.cleaned_data.items() if k in organization_specific_fields_names
            ]:
                setattr(self.instance, name, value)

    return OrganizationSpecificTableRowForm
