from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from django.db import models
from django.db.models.signals import class_prepared
from django.dispatch import receiver

from organizations.exceptions import OrganizationNotFoundError
from organizations.fields import expand_safe_relation_field_names, rewrite_safe_relation_kwargs
from organizations.helpers.organizations import get_current_organization
from organizations.managers import (
    MultipleOrganizationModelManager,
    MultipleOrganizationsUnscopedManager,
    SingleOrganizationModelManager,
    SingleOrganizationUnscopedManager,
)
from organizations.settings import get_setting

if TYPE_CHECKING:
    from organizations.models import Organization


def get_default_organization() -> Organization | None:
    from organizations.models import Organization

    return Organization.objects.filter(slug=get_setting('DEFAULT_ORGANIZATION_SLUG')).first()


class SingleOrganizationModelMixin(models.Model):
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        # No ``default=``. A callable default is evaluated in ``Model.__init__``
        # for every instantiation that does not pass ``organization=``, so
        # ``get_default_organization`` used to run one ``SELECT`` per model
        # constructed -- 100 of them before a ``bulk_create`` of 100 rows.
        # ``save()`` resolves the organization instead: once per saved row, and
        # only when the field was left empty.
        #
        # It also fixes an ordering bug. The default was applied at
        # construction, so with an organization actually named
        # ``DEFAULT_ORGANIZATION_SLUG`` in the database, every model built
        # without an explicit ``organization=`` was stamped with *that*
        # organization and saved into it, ignoring the one bound to the
        # context. The bound organization now wins and the default is only a
        # fallback.
        #
        # No ``db_index`` either: Django's single-column index on this column
        # is a prefix of the ``(organization, pk)`` index added below, so it
        # can never answer a query the composite cannot. Keeping both only
        # gives the planner a worse option -- it picks the narrow index and
        # then sorts, instead of walking the composite in primary key order and
        # stopping at the end of the page.
        db_index=False,
    )

    objects = SingleOrganizationModelManager()

    original_manager = SingleOrganizationUnscopedManager()
    organization_objects = SingleOrganizationModelManager()

    class Meta:
        abstract = True
        default_manager_name = 'objects'
        # Not ``objects``. ``_base_manager`` is the manager Django itself uses
        # for the operations that must see a row it already knows exists: the
        # ``UPDATE`` behind ``save()``, ``refresh_from_db()``, the cascade
        # collector behind ``delete()``, and fetching a forward relation. It is
        # documented as a manager that must not filter rows away, and pointing
        # it at the scoped manager broke each of those:
        #
        # * ``instance.save()`` on an existing row matched nothing, so Django
        #   fell through to an ``INSERT`` and raised ``IntegrityError`` on the
        #   duplicate primary key -- with no organization selected and *without*
        #   ``STRICT_ORGANIZATION_FILTER``, i.e. on the default settings.
        # * With ``STRICT_ORGANIZATION_FILTER`` on, all four raised
        #   ``OrganizationNotFoundError``, including saving an instance that had
        #   been handed an explicit ``organization``.
        #
        # Which of those a project hit depended on the order of its base
        # classes: ``Options.base_manager`` inherits ``base_manager_name`` from
        # the first parent in the MRO that has a ``_meta``, so
        # ``class M(SingleOrganizationModelMixin, TimeStampedModel)`` picked it
        # up and ``class M(TimeStampedModel, SingleOrganizationModelMixin)`` did
        # not.
        #
        # Reads still scope: ``objects`` is unchanged, and a relation declared
        # with ``OrganizationSafeForeignKey`` matches on the organization in its
        # own ``ON`` clause, so cross-organization traversal is prevented by the
        # join rather than by this manager.
        base_manager_name = 'original_manager'

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # ``article_id=5`` names the safe relation, whose column is really
        # ``article_fk_id``. Passing the instance instead (``article=article``)
        # needs no rewriting and is preferred: Django's descriptor copies the
        # target's organization across too.
        super().__init__(*args, **rewrite_safe_relation_kwargs(self.__class__, kwargs, rewrite_instances=False))

    def save(self, *args: Any, **kwargs: Any) -> None:
        if kwargs.get('update_fields') is not None:
            # ``update_fields=['article']`` names the safe relation, which is
            # not writable; it stands for ``article_fk`` and ``organization``.
            kwargs['update_fields'] = expand_safe_relation_field_names(self.__class__, kwargs['update_fields'])

        # ``organization_id``, not ``organization``: reading the relation goes
        # through the forward descriptor, which fetches the row from the
        # database whenever the id is set but no instance is cached -- a
        # ``SELECT`` on every single save, only to find out whether the field
        # had been filled in. The id answers the same question for free.
        if self.organization_id is None:
            organization = get_current_organization() or get_default_organization()

            if organization is None:
                raise OrganizationNotFoundError()

            # Assigning the instance rather than the id caches it on the
            # relation, so anything reading ``instance.organization`` after the
            # save does not go back to the database for it.
            self.organization = organization

        super().save(*args, **kwargs)


def organization_index_fields(model: type[models.Model]) -> list[str]:
    """The columns of the index every organization-scoped model should carry."""
    return ['organization', model._meta.pk.name]


def organization_index_exists(model: type[models.Model]) -> bool:
    """Has the model already declared the ``(organization, pk)`` index itself?"""
    fields = organization_index_fields(model)

    # Matched exactly rather than by leading column: a model that declares, say,
    # ``(organization, status)`` has covered one query shape and still needs the
    # primary-key-ordered index this replaces the foreign key's own index with.
    return any(index.fields == fields for index in model._meta.indexes)


@receiver(class_prepared)
def add_organization_index(sender: type[models.Model], **kwargs: Any) -> None:
    """Give every organization-scoped model an ``(organization, pk)`` index.

    This replaces the single-column index Django would have built for the
    foreign key, and it is the one index a scoped model cannot do without: the
    managers put ``organization`` in the ``WHERE`` clause of every query, so an
    index that does not lead with it cannot be used to find the rows.

    Adding the primary key as the second column costs nothing extra -- the
    index leaves already carry it -- and buys the common ``filter(...)`` /
    ``order_by('pk')`` / ``[:page]`` shape an ordered walk that stops at the
    end of the page, instead of a sort over every row the tenant owns.

    Built here rather than declared in ``Meta`` because the abstract base
    cannot know what a subclass calls its primary key, and a functional index
    over ``pk`` would need a name that is unique per model. A model that
    declares its own organization-leading index is left alone.
    """
    if not issubclass(sender, SingleOrganizationModelMixin) or sender._meta.abstract:
        return

    if organization_index_exists(sender):
        return

    index = models.Index(fields=organization_index_fields(sender))
    # ``Model._prepare()`` has already named the declared indexes by the time
    # this signal fires, so this one names itself the same way.
    index.set_name_with_model(sender)
    # ``Options.indexes`` is typed as "whatever ``Meta.indexes`` was", but
    # ``Meta`` here is the abstract base's, which declares none, so what a
    # subclass gets is the list ``Options`` built for it.
    indexes = cast('list[models.Index]', sender._meta.indexes)
    indexes.append(index)

    # ``ModelState.from_model`` only reads ``_meta.indexes`` for models whose
    # ``Meta`` actually declared ``indexes``, so without this the migration
    # autodetector never sees the index and no ``AddIndex`` is written. The
    # value is irrelevant -- the key's presence is what is checked.
    sender._meta.original_attrs.setdefault('indexes', indexes)


class MultipleOrganizationsModelMixin(models.Model):
    organizations = models.ManyToManyField('organizations.Organization')

    objects = MultipleOrganizationModelManager()

    organization_objects = MultipleOrganizationModelManager()
    original_manager = MultipleOrganizationsUnscopedManager()

    class Meta:
        abstract = True
        default_manager_name = 'objects'
        # See ``SingleOrganizationModelMixin.Meta`` -- ``_base_manager`` must
        # return every row for ``save()``, ``refresh_from_db()``, ``delete()``
        # and forward relations to work.
        base_manager_name = 'original_manager'

    def save(self, *args: Any, **kwargs: Any) -> None:
        organization = get_current_organization()

        if not organization:
            raise OrganizationNotFoundError()

        super().save(*args, **kwargs)
        self.organizations.add(organization)
