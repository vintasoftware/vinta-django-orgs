from __future__ import annotations

from collections import OrderedDict
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.fields import Field, SkipField, get_error_detail
from rest_framework.serializers import ModelSerializer

from organizations.utils import import_from_string
from organizations_custom_data.helpers.custom_tables_helpers import get_custom_table_manager
from organizations_custom_data.models import (
    OrganizationSpecificFieldDefinition,
    OrganizationSpecificTable,
    OrganizationSpecificTableRow,
)
from organizations_custom_data.settings import get_setting
from organizations_custom_data.utils import compose_list


class OrganizationSpecificFieldDefinitionCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationSpecificFieldDefinition
        fields = ['id', 'name', 'data_type', 'is_required', 'default_value', 'validators']

    def create(self, validated_date: dict[str, Any]) -> OrganizationSpecificFieldDefinition:
        table_content_type = getattr(self, 'table_content_type', None)
        table_id = getattr(self, 'table_id', None)

        validators = validated_date.pop('validators', [])
        definition = OrganizationSpecificFieldDefinition.objects.create(
            table_content_type=table_content_type, table_id=table_id, **validated_date
        )

        for v in validators:
            definition.validators.add(v)

        return definition


class OrganizationSpecificFieldDefinitionUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationSpecificFieldDefinition
        fields = ['id', 'is_required', 'default_value', 'validators']

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        instance = getattr(self, 'instance', None)
        if instance:
            is_required = data.get('is_required', instance.is_required)
            default_value = data.get('default_value', instance.default_value)

            if is_required and not default_value:
                raise serializers.ValidationError(
                    _(
                        'Your table already has data, so a new field must either be not required '
                        'or have a default value'
                    )
                )

        return data

    def update(
        self, instance: OrganizationSpecificFieldDefinition, validated_date: dict[str, Any]
    ) -> OrganizationSpecificFieldDefinition:
        instance.is_required = validated_date.get('is_required', instance.is_required)
        instance.default_value = validated_date.get('default_value', instance.default_value)
        instance.save()

        instance.validators.set(validated_date.get('validators', instance.validators))

        return instance


class OrganizationSpecificFieldsModelDefinitionsUpdateSerializer(serializers.ModelSerializer):
    fields_definitions = serializers.JSONField()

    class Meta:
        model = ContentType
        fields = ['fields_definitions']

    def to_representation(self, obj: ContentType) -> dict[str, Any]:
        return {
            'name': '%s%s%s'
            % (get_setting('CUSTOM_TABLES_LABEL'), get_setting('CUSTOMIZABLE_TABLES_LABEL_SEPARATOR'), obj.name),
            'fields_definitions': OrganizationSpecificFieldDefinitionCreateSerializer(
                OrganizationSpecificFieldDefinition.objects.filter(table_content_type=obj), many=True
            ).data,
        }

    def validate_fields_definitions(self, definitions: list[dict[str, Any]]) -> dict[str, Any]:
        definitions_errors: list[Any] = []
        definitions_serializers: list[ModelSerializer[Any]] = []
        definitions_have_errors = False
        new_definitions_ids = [y['id'] for y in definitions if y.get('id', False)]
        for definition_dict in definitions:
            definition_serializer: ModelSerializer[Any]

            if definition_dict.get('id', False):
                definition_serializer = OrganizationSpecificFieldDefinitionUpdateSerializer(
                    OrganizationSpecificFieldDefinition.objects.get(id=definition_dict.get('id')),
                    data=definition_dict,
                    context=self.context,
                )
            else:
                definition_serializer = OrganizationSpecificFieldDefinitionCreateSerializer(
                    data=definition_dict, context=self.context
                )

            if definition_serializer.is_valid():
                definitions_errors.append({})
                definitions_serializers.append(definition_serializer)
            else:
                definitions_errors.append(definition_serializer.errors)
                definitions_have_errors = True

        if definitions_have_errors:
            raise serializers.ValidationError(definitions_errors)

        return {
            'serializers': definitions_serializers,
            'deleted': OrganizationSpecificFieldDefinition.objects.filter(table_content_type=self.instance).exclude(
                id__in=new_definitions_ids
            ),
        }

    def update(self, instance: ContentType, validated_data: dict[str, Any]) -> ContentType:
        if self.validated_data.get('fields_definitions', False):
            self.validated_data['fields_definitions']['deleted'].delete()
            for definitions_serializer in self.validated_data['fields_definitions']['serializers']:
                definitions_serializer.table_content_type = instance
                definitions_serializer.save()

        return instance


class OrganizationSpecificTableSerializer(serializers.ModelSerializer):
    fields_definitions = serializers.JSONField()

    class Meta:
        model = OrganizationSpecificTable
        fields = ['name', 'fields_definitions']

    def to_representation(self, obj: OrganizationSpecificTable) -> dict[str, Any]:
        return {
            'name': '%s%s%s'
            % (get_setting('CUSTOM_TABLES_LABEL'), get_setting('CUSTOMIZABLE_TABLES_LABEL_SEPARATOR'), obj.name),
            'fields_definitions': OrganizationSpecificFieldDefinitionCreateSerializer(
                obj.fields_definitions, many=True
            ).data,
        }

    def validate_name(self, name: str) -> str:
        table_slug_parts = name.split(get_setting('CUSTOMIZABLE_TABLES_LABEL_SEPARATOR'))
        app = table_slug_parts[0]

        if app != get_setting('CUSTOM_TABLES_LABEL') or len(table_slug_parts) < 2:
            raise serializers.ValidationError(_('This is not a valid custom table name'))

        return table_slug_parts[-1]

    def validate_fields_definitions(self, definitions: list[dict[str, Any]]) -> dict[str, Any]:
        definitions_errors: list[Any] = []
        definitions_serializers: list[ModelSerializer[Any]] = []
        definitions_have_errors = False
        new_definitions_ids = [y['id'] for y in definitions if y.get('id', False)]
        for definition_dict in definitions:
            definition_serializer: ModelSerializer[Any]

            if definition_dict.get('id', False):
                definition_serializer = OrganizationSpecificFieldDefinitionUpdateSerializer(
                    OrganizationSpecificFieldDefinition.objects.get(id=definition_dict.get('id')),
                    data=definition_dict,
                    context=self.context,
                )
            else:
                definition_serializer = OrganizationSpecificFieldDefinitionCreateSerializer(
                    data=definition_dict, context=self.context
                )

            if definition_serializer.is_valid():
                definitions_errors.append({})
                definitions_serializers.append(definition_serializer)
            else:
                definitions_errors.append(definition_serializer.errors)
                definitions_have_errors = True

        if definitions_have_errors:
            raise serializers.ValidationError(definitions_errors)

        return {
            'serializers': definitions_serializers,
            'deleted': self.instance.fields_definitions.exclude(id__in=new_definitions_ids) if self.instance else None,
        }

    def create(self, validated_data: dict[str, Any]) -> OrganizationSpecificTable:
        table_name = validated_data.get('name')
        table = OrganizationSpecificTable.objects.create(name=table_name)

        if self.validated_data.get('fields_definitions', False):
            for definitions_serializer in self.validated_data['fields_definitions']['serializers']:
                definitions_serializer.table_id = table.id
                definitions_serializer.table_content_type = ContentType.objects.get_for_model(
                    OrganizationSpecificTable
                )
                definitions_serializer.save()

        return table

    def update(self, instance: OrganizationSpecificTable, validated_data: dict[str, Any]) -> OrganizationSpecificTable:
        if validated_data.get('name', False):
            table_name = validated_data['name']
            instance.name = table_name
            instance.save()

        if self.validated_data.get('fields_definitions', False):
            self.validated_data['fields_definitions']['deleted'].delete()
            table_content_type = ContentType.objects.get_for_model(OrganizationSpecificTable)
            for definitions_serializer in self.validated_data['fields_definitions']['serializers']:
                definitions_serializer.table_id = instance.id
                definitions_serializer.table_content_type = table_content_type
                definitions_serializer.save()

        return instance


def bind_placeholder_model_field(
    model_field: models.Field[Any, Any], field_name: str, model_class: type[models.Model]
) -> models.Field[Any, Any]:
    """
    Organization specific fields are stored in pivot tables, so the model has no
    real field for them. `ModelSerializer.build_standard_field` inspects the
    field's name and its `model` attribute, so hand it a detached clone bound to
    the serialized model instead of the shared placeholder instance.
    """
    model_field = model_field.clone()
    model_field.set_attributes_from_name(field_name)
    model_field.model = model_class
    return model_field


class OrganizationSpecificModelSerializer(serializers.ModelSerializer):
    serializer_organization_specific_field_mapping: dict[str, type[Field]] = {
        'integer': serializers.IntegerField,
        'char': serializers.CharField,
        'text': serializers.CharField,
        'float': serializers.FloatField,
        'datetime': serializers.DateTimeField,
        'date': serializers.DateField,
    }

    data_type_fields: dict[str, models.Field[Any, Any]] = {
        'integer': models.IntegerField(),
        'char': models.CharField(max_length=255),
        'text': models.TextField(),
        'float': models.FloatField(),
        'datetime': models.DateTimeField(),
        'date': models.DateField(),
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        ModelClass = self.Meta.model

        self.organization_specific_fields_definitions = OrganizationSpecificFieldDefinition.objects.filter(
            table_content_type=ContentType.objects.get_for_model(ModelClass)
        )

        self.organization_specific_fields_names = list(
            self.organization_specific_fields_definitions.values_list('name', flat=True)
        )

        for definition in self.organization_specific_fields_definitions:
            if not hasattr(self, definition.name):
                field_kwargs: dict[str, Any] = {}
                if definition.is_required:
                    field_kwargs.update({'required': True, 'allow_null': True})
                if definition.default_value is not None:
                    field_kwargs.update({'default': definition.default_value})

                setattr(
                    self,
                    definition.name,
                    self.serializer_organization_specific_field_mapping[definition.data_type](**field_kwargs),
                )

        super().__init__(*args, **kwargs)

    def get_field_names(self, declared_fields: Any, info: Any) -> list[str]:
        fields = super().get_field_names(declared_fields, info)
        return fields + self.organization_specific_fields_names

    def to_internal_value(self, data: Any) -> Any:
        ret: OrderedDict[str, Any] = OrderedDict()
        errors: OrderedDict[str, Any] = OrderedDict()

        for field in self.organization_specific_fields_definitions:
            validators = []
            for validator_instance in field.validators.all():
                validator_function = import_from_string(validator_instance.module_path)
                validators.append(validator_function)

            validate_method = compose_list(validators)

            serializer_field = self.fields[field.name]
            primitive_value = serializer_field.get_value(data)
            try:
                validated_value = serializer_field.run_validation(primitive_value)
                if validate_method is not None:
                    validated_value = validate_method(validated_value)
            except serializers.ValidationError as exc:
                errors[field.name] = exc.detail
            except DjangoValidationError as exc:
                errors[field.name] = get_error_detail(exc)
            except SkipField:
                pass
            else:
                self.set_value(ret, serializer_field.source_attrs, validated_value)

        if errors:
            raise serializers.ValidationError(errors)

        data.update(dict(ret))

        ret = super().to_internal_value(data)

        return ret

    def build_field(
        self, field_name: str, info: Any, model_class: type[models.Model], nested_depth: int
    ) -> tuple[type[Field], dict[str, Any]]:
        tenat_specific_fields_names = list(
            self.organization_specific_fields_definitions.values_list('name', flat=True)
        )
        if field_name in tenat_specific_fields_names:
            definition = self.organization_specific_fields_definitions.get(name=field_name)
            return self.build_standard_field(
                field_name,
                bind_placeholder_model_field(self.data_type_fields[definition.data_type], field_name, model_class),
            )

        return super().build_field(field_name, info, model_class, nested_depth)

    def create(self, validated_data: dict[str, Any]) -> Any:
        # ``Meta.model`` is the serialized model, whose manager annotates the
        # organization specific fields; the freshly created row is re-read so
        # those annotations are populated.
        ModelClass: Any = self.Meta.model
        instance = ModelClass.objects.create(**validated_data)
        return ModelClass.objects.get(pk=instance.pk)

    def update(self, instance: Any, validated_data: dict[str, Any]) -> Any:
        ModelClass: Any = self.Meta.model
        instance = super().update(instance, validated_data)
        return ModelClass.objects.get(pk=instance.pk)


def get_organization_specific_table_row_serializer_class(table_name: str) -> type[ModelSerializer[Any]]:

    organization_specific_fields_definitions = OrganizationSpecificFieldDefinition.objects.filter(
        table_content_type=ContentType.objects.get_for_model(OrganizationSpecificTable),
        table_id__in=OrganizationSpecificTable.objects.filter(name=table_name).values_list('id', flat=True),
    )

    class OrganizationSpecificTableRowSerializer(serializers.ModelSerializer):
        class Meta:
            model = OrganizationSpecificTableRow
            fields = ['id'] + list(organization_specific_fields_definitions.values_list('name', flat=True))

        serializer_organization_specific_field_mapping: dict[str, type[Field]] = {
            'integer': serializers.IntegerField,
            'char': serializers.CharField,
            'text': serializers.CharField,
            'float': serializers.FloatField,
            'datetime': serializers.DateTimeField,
            'date': serializers.DateField,
        }

        data_type_fields: dict[str, models.Field[Any, Any]] = {
            'integer': models.IntegerField(),
            'char': models.CharField(max_length=255),
            'text': models.TextField(),
            'float': models.FloatField(),
            'datetime': models.DateTimeField(),
            'date': models.DateField(),
        }

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            for definition in organization_specific_fields_definitions:
                field_kwargs: dict[str, Any] = {}
                if definition.is_required:
                    field_kwargs.update({'required': True, 'allow_null': True})
                if definition.default_value is not None:
                    field_kwargs.update({'default': definition.default_value})

                setattr(
                    self,
                    definition.name,
                    self.serializer_organization_specific_field_mapping[definition.data_type](**field_kwargs),
                )

            super().__init__(*args, **kwargs)

        def to_internal_value(self, data: Any) -> Any:
            ret: OrderedDict[str, Any] = OrderedDict()
            errors: OrderedDict[str, Any] = OrderedDict()

            for field in organization_specific_fields_definitions:
                validators = []
                for validator_instance in field.validators.all():
                    validator_function = import_from_string(validator_instance.module_path)
                    validators.append(validator_function)

                validate_method = compose_list(validators)

                serializer_field = self.fields[field.name]
                primitive_value = serializer_field.get_value(data)
                try:
                    validated_value = serializer_field.run_validation(primitive_value)
                    if validate_method is not None:
                        validated_value = validate_method(validated_value)
                except serializers.ValidationError as exc:
                    errors[field.name] = exc.detail
                except DjangoValidationError as exc:
                    errors[field.name] = get_error_detail(exc)
                except SkipField:
                    pass
                else:
                    self.set_value(ret, serializer_field.source_attrs, validated_value)

            if errors:
                raise serializers.ValidationError(errors)

            data.update(dict(ret))

            ret = super().to_internal_value(data)

            return ret

        def build_field(
            self, field_name: str, info: Any, model_class: type[models.Model], nested_depth: int
        ) -> tuple[type[Field], dict[str, Any]]:
            if field_name in list(organization_specific_fields_definitions.values_list('name', flat=True)):
                definition = organization_specific_fields_definitions.get(name=field_name)
                return self.build_standard_field(
                    field_name,
                    bind_placeholder_model_field(self.data_type_fields[definition.data_type], field_name, model_class),
                )

            return super().build_field(field_name, info, model_class, nested_depth)

        def create(self, validated_data: dict[str, Any]) -> OrganizationSpecificTableRow:
            instance = get_custom_table_manager(table_name).create(**validated_data)
            return get_custom_table_manager(table_name).get(pk=instance.pk)

        def update(
            self, instance: OrganizationSpecificTableRow, validated_data: dict[str, Any]
        ) -> OrganizationSpecificTableRow:
            instance = super().update(instance, validated_data)
            return get_custom_table_manager(table_name).get(pk=instance.pk)

    return OrganizationSpecificTableRowSerializer
