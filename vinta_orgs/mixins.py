from __future__ import annotations

from typing import TYPE_CHECKING, Any

from asgiref.sync import sync_to_async
from django.db import models, router, transaction
from django.db.models.signals import class_prepared
from django.dispatch import receiver

from vinta_orgs._organization_updates import organization_update_is_allowed
from vinta_orgs._state import get_bound_organization
from vinta_orgs.conf import get_organization_model, organization_model_string
from vinta_orgs.exceptions import OrganizationCannotBeUpdatedError, OrganizationNotFoundError
from vinta_orgs.fields import expand_safe_relation_field_names, rewrite_safe_relation_kwargs
from vinta_orgs.managers import (
    MultipleOrganizationModelManager,
    MultipleOrganizationsUnscopedManager,
    SingleOrganizationModelManager,
    SingleOrganizationUnscopedManager,
    unscoped_default_manager,
)
from vinta_orgs.settings import get_setting

if TYPE_CHECKING:
    from vinta_orgs.models import AbstractOrganization


def get_default_organization() -> AbstractOrganization | None:
    slug = get_setting('DEFAULT_ORGANIZATION_SLUG')

    # ``DEFAULT_ORGANIZATION_SLUG = None`` is how a project says it has no
    # catch-all organization, which is the right setting whenever every row must
    # belong to an organization the caller selected. Without this the ``save()``
    # fallback below still ran ``WHERE slug IS NULL`` -- a query that can never
    # match a column declared ``NOT NULL`` -- once per saved row, immediately
    # before raising ``OrganizationNotFoundError`` anyway.
    if not slug:
        return None

    # ``_default_manager`` rather than ``objects``: the model is whatever
    # ``ORGANIZATION_MODEL`` names, and a project is free to call its manager
    # something else.
    return get_organization_model()._default_manager.filter(slug=slug).first()


def _model_pk_is_set(instance: models.Model) -> bool:
    """Django's private ``_is_pk_set()``, expressed from the public ``pk`` value."""
    pk = instance.pk
    return pk is not None and (not isinstance(pk, tuple) or all(value is not None for value in pk))


class SingleOrganizationModelMixin(models.Model):
    organization = models.ForeignKey(
        # Resolved once, at class-definition time, from ``ORGANIZATION_MODEL`` --
        # so a project that swapped the organization model gets foreign keys to
        # *its* table on every scoped model, its own included.
        organization_model_string(),
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
        # * Under ``STRICT_ORGANIZATION_FILTER`` -- the default -- all four
        #   raised ``OrganizationNotFoundError`` with no organization selected,
        #   including saving an instance that had been handed an explicit
        #   ``organization``.
        # * With the setting cleared, ``instance.save()`` on an existing row
        #   matched nothing, so Django fell through to an ``INSERT`` and raised
        #   ``IntegrityError`` on the duplicate primary key.
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
        unsafe_organization_update = kwargs.pop('unsafe_organization_update', False)

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
            organization = get_bound_organization() or get_default_organization()

            if organization is None:
                raise OrganizationNotFoundError()

            # Assigning the instance rather than the id caches it on the
            # relation, so anything reading ``instance.organization`` after the
            # save does not go back to the database for it.
            self.organization = organization

        update_fields = kwargs.get('update_fields')
        writes_organization = update_fields is None or bool(
            {'organization', 'organization_id'}.intersection(update_fields)
        )
        force_insert = kwargs.get('force_insert', False)

        if (
            writes_organization
            and _model_pk_is_set(self)
            and not force_insert
            and not unsafe_organization_update
            and not organization_update_is_allowed()
        ):
            using = kwargs.get('using') or router.db_for_write(self.__class__, instance=self)

            with transaction.atomic(using=using):
                persisted = (
                    self.__class__._base_manager.using(using)
                    .select_for_update()
                    .filter(pk=self.pk)
                    .values_list('pk', 'organization_id')
                    .first()
                )

                if persisted is not None and persisted[1] != self.organization_id:
                    raise OrganizationCannotBeUpdatedError()

                super().save(*args, **kwargs)
            return

        super().save(*args, **kwargs)

    async def asave(self, *args: Any, **kwargs: Any) -> None:
        return await sync_to_async(self.save)(*args, **kwargs)

    def validate_unique(self, exclude: Any = None) -> None:
        with unscoped_default_manager():
            super().validate_unique(exclude=exclude)

    def validate_constraints(self, exclude: Any = None) -> None:
        with unscoped_default_manager():
            super().validate_constraints(exclude=exclude)


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
    indexes = sender._meta.indexes
    if not isinstance(indexes, list):
        indexes = list(indexes)
        sender._meta.indexes = indexes
    indexes.append(index)

    # ``ModelState.from_model`` only reads ``_meta.indexes`` for models whose
    # ``Meta`` actually declared ``indexes``, so without this the migration
    # autodetector never sees the index and no ``AddIndex`` is written. The
    # value is irrelevant -- the key's presence is what is checked.
    sender._meta.original_attrs.setdefault('indexes', indexes)


class MultipleOrganizationsModelMixin(models.Model):
    # Annotated explicitly: the target is a runtime call rather than a literal,
    # so the type checker cannot infer what this relates to.
    organizations: models.ManyToManyField[AbstractOrganization, Any] = models.ManyToManyField(
        organization_model_string()
    )

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
        organization = get_bound_organization()

        if not organization:
            raise OrganizationNotFoundError()

        super().save(*args, **kwargs)
        self.organizations.add(organization)

    def validate_unique(self, exclude: Any = None) -> None:
        with unscoped_default_manager():
            super().validate_unique(exclude=exclude)

    def validate_constraints(self, exclude: Any = None) -> None:
        with unscoped_default_manager():
            super().validate_constraints(exclude=exclude)
