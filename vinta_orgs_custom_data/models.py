from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from model_utils.choices import Choices
from model_utils.fields import StatusField
from model_utils.models import TimeStampedModel

from vinta_orgs.conf import organization_model_string
from vinta_orgs.mixins import MultipleOrganizationsModelMixin, SingleOrganizationModelMixin
from vinta_orgs_custom_data.managers import OrganizationSpecificTableRowManager
from vinta_orgs_custom_data.mixins import OrganizationSpecificFieldsModelMixin, OrganizationSpecificPivotTable

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from vinta_orgs.models import AbstractOrganization, AbstractOrganizationMembership


class OrganizationSpecificTable(SingleOrganizationModelMixin):
    name = models.CharField(max_length=255)

    class Meta:
        unique_together = [('organization', 'name')]

    def __str__(self) -> str:
        return '%s/%s' % (self.organization.slug, self.name)

    @property
    def fields_definitions(self) -> QuerySet[OrganizationSpecificFieldDefinition]:
        return OrganizationSpecificFieldDefinition.objects.filter(
            table_content_type=ContentType.objects.get_for_model(OrganizationSpecificTable), table_id=self.id
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        super().save(*args, **kwargs)
        tstgroup = OrganizationSpecificTablesGroup.objects.get(group__name='organization_owner')
        tstgroup.permissions.add(
            OrganizationSpecificTablesPermission.objects.create(name='add', table=self, codename='add_' + self.name)
        )
        tstgroup.permissions.add(
            OrganizationSpecificTablesPermission.objects.create(
                name='change', table=self, codename='change_' + self.name
            )
        )
        tstgroup.permissions.add(
            OrganizationSpecificTablesPermission.objects.create(
                name='delete', table=self, codename='delete_' + self.name
            )
        )


class OrganizationSpecificTablesPermission(SingleOrganizationModelMixin):
    name = models.CharField(max_length=255)
    table = models.ForeignKey('OrganizationSpecificTable', on_delete=models.CASCADE)
    codename = models.CharField(max_length=100)


class OrganizationSpecificTablesGroup(SingleOrganizationModelMixin):
    group = models.ForeignKey(Group, related_name='organization_specific_tables_groups', on_delete=models.CASCADE)
    permissions = models.ManyToManyField(
        'vinta_orgs_custom_data.OrganizationSpecificTablesPermission', blank=True, related_name='groups'
    )

    class Meta:
        unique_together = ['group', 'organization']


@receiver(post_save, sender=Group)
def create_organization_specific_tables_group(
    sender: type[Group], instance: Group, created: bool, *args: Any, **kwargs: Any
) -> None:
    if created:
        new_group = OrganizationSpecificTablesGroup.objects.create(group=instance)
        if instance.name == 'organization_owner':
            for perm in OrganizationSpecificTablesPermission.objects.all():
                new_group.permissions.add(perm)


class OrganizationSpecificTablesRelationship(SingleOrganizationModelMixin):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    groups = models.ManyToManyField(
        'vinta_orgs_custom_data.OrganizationSpecificTablesGroup', related_name='relationships'
    )
    permissions = models.ManyToManyField(
        'vinta_orgs_custom_data.OrganizationSpecificTablesPermission', related_name='relationships'
    )


# Connected in ``OrganizationsCustomDataConfig.ready()`` rather than decorated:
# the membership model is swappable, so the sender is only known once the app
# registry is populated.
def create_organization_specific_tables_relationship(
    sender: type[AbstractOrganizationMembership],
    instance: AbstractOrganizationMembership,
    created: bool,
    *args: Any,
    **kwargs: Any,
) -> None:
    if created:
        new_rel = OrganizationSpecificTablesRelationship.objects.create(
            user=instance.user, organization=instance.organization
        )
        for group in instance.groups.all():
            tstgroup = OrganizationSpecificTablesGroup.objects.get(group=group)
            new_rel.groups.add(tstgroup)


# Likewise connected from ``ready()`` -- the sender is the configured membership
# model's ``groups`` through table.
def add_group_organization_specific_tables_relationship(
    sender: type[Any], instance: AbstractOrganizationMembership, action: str, *args: Any, **kwargs: Any
) -> None:
    if action == 'post_add':
        rel, created = OrganizationSpecificTablesRelationship.objects.get_or_create(
            user=instance.user, organization=instance.organization
        )
        for group in instance.groups.all():
            tstgroup = OrganizationSpecificTablesGroup.objects.get(group=group)
            rel.groups.add(tstgroup)


class OrganizationSpecificFieldsValidator(MultipleOrganizationsModelMixin):
    module_path = models.CharField(max_length=255)
    # Redeclared only to name the reverse accessor, which gives the field --
    # and so its related manager -- a type of its own. Annotated explicitly
    # because the target is a runtime call rather than a literal, so the type
    # checker cannot infer what it relates to.
    organizations: models.ManyToManyField[AbstractOrganization, Any] = models.ManyToManyField(
        organization_model_string(), related_name='validators_available'
    )

    def __str__(self) -> str:
        return self.module_path


class OrganizationSpecificFieldDefinition(SingleOrganizationModelMixin):
    name = models.CharField(max_length=255)
    DATA_TYPES = Choices('char', 'text', 'integer', 'float', 'datetime', 'date')
    data_type = StatusField(choices_name='DATA_TYPES')
    is_required = models.BooleanField(default=False)
    default_value = models.TextField()
    validators = models.ManyToManyField('vinta_orgs_custom_data.OrganizationSpecificFieldsValidator', blank=True)

    table_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    table_id = models.PositiveIntegerField(blank=True, null=True)

    class Meta:
        unique_together = [('organization', 'table_id', 'table_content_type', 'name')]

    def __str__(self) -> str:
        content_type = '%s/%s' % (self.organization.slug, str(self.table_content_type))
        # FIXME: this branch is dead and broken on both counts. ``content_type``
        # is built above as "<organization slug>/<content type>", so it can
        # never equal the bare label compared against; and this model points at
        # its table through ``table_content_type``/``table_id`` -- there is no
        # ``table`` attribute to read, so the branch would raise if it were
        # ever reached. Deciding what a definition on a custom table should
        # render as is a product call, so it is left as-is and flagged here.
        if content_type == 'vinta_orgs.OrganizationSpecificTable':
            content_type = str(self.table)  # type: ignore[attr-defined]

        return '%s.%s' % (content_type, self.name)


class OrganizationSpecificFieldIntegerPivot(SingleOrganizationModelMixin, OrganizationSpecificPivotTable):
    value = models.IntegerField()

    def __str__(self) -> str:
        return '%s: %d' % (str(self.definition), self.value)


class OrganizationSpecificFieldCharPivot(SingleOrganizationModelMixin, OrganizationSpecificPivotTable):
    value = models.CharField(max_length=255)


class OrganizationSpecificFieldTextPivot(SingleOrganizationModelMixin, OrganizationSpecificPivotTable):
    value = models.TextField()


class OrganizationSpecificFieldFloatPivot(SingleOrganizationModelMixin, OrganizationSpecificPivotTable):
    value = models.FloatField()

    def __str__(self) -> str:
        return '%s: %f' % (str(self.definition), self.value)


class OrganizationSpecificFieldDatePivot(SingleOrganizationModelMixin, OrganizationSpecificPivotTable):
    value = models.DateField()

    def __str__(self) -> str:
        return '%s: %s' % (str(self.definition), self.value.isoformat())


class OrganizationSpecificFieldDateTimePivot(SingleOrganizationModelMixin, OrganizationSpecificPivotTable):
    value = models.DateTimeField()

    def __str__(self) -> str:
        return '%s: %s' % (str(self.definition), self.value.isoformat())


class OrganizationSpecificTableRow(
    TimeStampedModel, SingleOrganizationModelMixin, OrganizationSpecificFieldsModelMixin
):
    table = models.ForeignKey('OrganizationSpecificTable', related_name='rows', on_delete=models.CASCADE)

    # All three replace the managers ``SingleOrganizationModelMixin`` installs:
    # a row's custom fields live in the pivot tables, so its queryset has to
    # annotate them, which is what ``OrganizationSpecificTableRowManager``
    # adds. ``original_manager`` is a plain one on purpose -- it is the escape
    # hatch that reads rows without any of that.
    objects: ClassVar[OrganizationSpecificTableRowManager] = OrganizationSpecificTableRowManager()

    # Narrower than the mixin's, deliberately: the mixin's ``original_manager``
    # still offers the scoping methods, and this one is a plain manager so that
    # ``Meta.default_manager_name`` points at something that needs no
    # ``table_id``. Code holding the mixin cannot assume the scoping methods on
    # this model, which is what the type checker is objecting to.
    original_manager: ClassVar[models.Manager[Any]] = models.Manager()  # type: ignore[assignment]
    organization_objects: ClassVar[OrganizationSpecificTableRowManager] = OrganizationSpecificTableRowManager()

    class Meta:
        default_manager_name = 'original_manager'
        base_manager_name = 'original_manager'

    def __str__(self) -> str:
        return ', '.join(str(p) for p in self.pivots)

    @property
    def fields_definitions(self) -> QuerySet[OrganizationSpecificFieldDefinition]:
        return self.table.fields_definitions

    @property
    def values_dict(self) -> dict[str, Any]:
        from vinta_orgs_custom_data.helpers.custom_tables_helpers import _get_pivot_table_class_for_data_type

        definitions = self.table.fields_definitions
        row_content_type = ContentType.objects.get_for_model(self.__class__)
        values = {
            d.name: _get_pivot_table_class_for_data_type(d.data_type)
            .objects.get(row_id=self.id, row_content_type=row_content_type)
            .value
            for d in definitions
        }

        return values

    @property
    def pivots(self) -> dict[str, Any]:
        from vinta_orgs_custom_data.helpers.custom_tables_helpers import _get_pivot_table_class_for_data_type

        definitions = self.table.fields_definitions
        row_content_type = ContentType.objects.get_for_model(self.__class__)
        values_list = {
            d.name: _get_pivot_table_class_for_data_type(d.data_type).objects.get(
                row_id=self.id, row_content_type=row_content_type
            )
            for d in definitions
        }

        return values_list

    def update_organization_specific_fields(self, organization_specific_fields_data: dict[str, Any]) -> None:
        from vinta_orgs_custom_data.helpers.custom_tables_helpers import (
            _get_pivot_table_class_for_data_type,
            get_custom_table_manager,
        )

        old = get_custom_table_manager(self.table.name).get(pk=self.pk)
        definitions = self.get_definitions()
        definitions_by_name = {d.name: d for d in definitions}

        with transaction.atomic():
            for field_name, definition in definitions_by_name.items():
                new_value = organization_specific_fields_data.get(field_name, None)
                old_value = getattr(old, field_name, None)
                if new_value != old_value:
                    PivotTableClass = _get_pivot_table_class_for_data_type(definition.data_type)
                    PivotTableClass.objects.filter(
                        definition__id=definition.id,
                        row_id=self.id,
                        row_content_type=ContentType.objects.get_for_model(self.__class__),
                    ).update(value=new_value)
