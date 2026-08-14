"""Relations that carry the organization into the JOIN's ON clause.

A plain ``ForeignKey`` between two organization-aware models joins on the key
alone::

    JOIN articles_article ON (articles_article.id = articles_comment.article_id)

Nothing in that join says the two rows belong to the same organization. The
managers scope the *outermost* query, but a relation traversal --
``select_related('article')``, ``comment.article``, ``filter(article__title=…)``
-- reaches whatever row the key points at. One bad write, one data migration, or
one row created while a different organization was selected, and a query returns
another organization's data through a relation the manager never looked at.

These fields make the organization part of the join itself::

    JOIN articles_article ON (articles_article.id = articles_comment.article_fk_id
                          AND articles_article.organization_id = articles_comment.organization_id)

A mismatched row simply does not join: it reads as missing rather than as
someone else's data.

How it works
------------
The declared name is contributed *twice*:

* ``<name>_fk`` -- a real ``ForeignKey``/``OneToOneField``. It owns the column,
  the database constraint, the cascade behaviour and the admin widget.
* ``<name>`` -- a non-concrete ``ForeignObject`` joining
  ``(<name>_fk, organization)`` to ``(<target pk>, organization)``. It adds no
  column of its own; it is the relation everything should traverse.

So the good name is the safe one, and reading, filtering and ``select_related``
are organization-checked by default. ``SingleOrganizationModelMixin`` rewrites
``<name>=``/``<name>_id=`` keyword arguments onto the concrete field, so writing
still looks like an ordinary foreign key.

Both models must be organization-aware -- the join reads ``organization_id`` on
each side.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, TypeVar

from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.models.fields.related import ForeignObject
from django.db.models.fields.related_descriptors import ForwardManyToOneDescriptor, ReverseOneToOneDescriptor

_RelatedModelT = TypeVar('_RelatedModelT', bound=models.Model)

if TYPE_CHECKING:
    _OrganizationSafeRelationBase = models.Field[_RelatedModelT, _RelatedModelT]
else:
    _OrganizationSafeRelationBase = models.Field


class OrganizationSafeForwardManyToOneDescriptor(ForwardManyToOneDescriptor):
    """Preserve the source organization when a safe relation is cleared.

    Django's descriptor normally writes ``None`` to every local join column.
    That is correct for a generic ``ForeignObject``, but one of this relation's
    columns is the row's tenant key rather than part of the nullable target key.
    """

    def __set__(self, instance: models.Model, value: models.Model | None) -> None:
        if value is not None:
            super().__set__(instance, value)
            return

        remote_field = self.field.remote_field
        related = self.field.get_cached_value(instance, default=None)

        if related is not None:
            remote_field.set_cached_value(related, None)

        # Safe relations always put the row's organization second in
        # ``from_fields``; derive it from the field's declared shape instead of
        # attaching an untyped ad-hoc attribute to the field instance.
        organization_field_name = self.field.from_fields[-1]

        for local_field, _remote_field in self.field.related_fields:
            if local_field.name != organization_field_name:
                # Use the attname so a concrete ForeignKey's descriptor also
                # invalidates its own cached related instance.
                setattr(instance, local_field.attname, None)

        self.field.set_cached_value(instance, None)


class OrganizationSafeOneToOneObject(ForeignObject):
    """``ForeignObject`` that behaves like a one-to-one on the reverse side.

    ``ForeignObject`` always installs the many-to-one reverse accessor, so
    ``article.statistics`` would hand back a manager even though the underlying
    relation is unique. Swapping in the one-to-one descriptor makes the reverse
    side return the instance (or raise ``DoesNotExist``), which is what
    declaring a one-to-one promises.
    """

    one_to_one = True
    many_to_one = False
    forward_related_accessor_class = OrganizationSafeForwardManyToOneDescriptor
    # Deliberately not the ``ReverseManyToOneDescriptor`` the base class
    # declares -- swapping in the one-to-one descriptor is the whole point of
    # this subclass, and the two are siblings rather than subclasses.
    related_accessor_class: type[Any] = ReverseOneToOneDescriptor


class OrganizationSafeRelation(_OrganizationSafeRelationBase):
    """Contributes the concrete relation plus its organization-checked twin.

    The declaration subclasses ``Field`` so django-stubs treats it like a model
    field, but it is never registered under its own identity. Its
    ``contribute_to_class`` implementation instead installs the two fields
    described above.
    """

    #: The concrete relation contributed as ``<name>_fk``.
    concrete_field_class: type[models.ForeignKey[Any, Any]] = models.ForeignKey
    #: The non-concrete twin contributed under the declared name.
    safe_field_class: type[ForeignObject] = ForeignObject
    #: Extra keyword arguments for the twin.
    foreign_object_kwargs: dict[str, Any] = {}
    #: Suffix for the reverse accessor of the concrete relation. The safe
    #: relation keeps the plain ``related_name``, so the two cannot collide.
    concrete_related_name_suffix = '_fk_rel'
    #: Default suffix for the safe relation's reverse accessor.
    default_related_name_suffix = '_set'

    def __init__(
        self,
        to: type[_RelatedModelT] | str,
        on_delete: Callable[..., Any] = models.CASCADE,
        related_name: str | None = None,
        null: bool = False,
        blank: bool = False,
        help_text: str = '',
        organization_field: str = 'organization',
        **kwargs: Any,
    ) -> None:
        # The declaration is a ``Field`` for django-stubs and model-declaration
        # introspection, but contributes only the two fields built below.
        super().__init__(null=null, blank=blank, help_text=help_text)
        self.to = to
        self.on_delete = on_delete
        self.related_name = related_name
        self.null = null
        self.blank = blank
        self.help_text = help_text
        self.organization_field = organization_field
        self.extra_kwargs = kwargs

    def contribute_to_class(
        self, cls: type[models.Model], name: str, private_only: bool = False, **kwargs: Any
    ) -> None:
        concrete_name = '%s_fk' % name
        related_name = self.related_name or '%s%s' % (name, self.default_related_name_suffix)

        concrete_field = self.concrete_field_class(
            self.to,
            on_delete=self.on_delete,
            related_name='%s%s' % (self.related_name or name, self.concrete_related_name_suffix),
            null=self.null,
            blank=self.blank,
            help_text=self.help_text,
            **self.extra_kwargs,
        )
        concrete_field.contribute_to_class(cls, concrete_name)

        safe_field = self.safe_field_class(
            self.to,
            # Field names, not attnames: ``Options.get_field`` resolves by name.
            from_fields=[concrete_name, self.organization_field],
            # ``None`` means "the target's primary key", so this works whatever
            # the target calls its key and whatever type it is. django-stubs
            # types ``to_fields`` as a sequence of names and leaves out the
            # ``None`` that Django itself accepts here.
            to_fields=[None, self.organization_field],  # type: ignore[list-item]
            on_delete=self.on_delete,
            related_name=related_name,
            editable=False,
            null=self.null,
            **self.foreign_object_kwargs,
        )
        # Kept on the field instance rather than expressed as a new
        # ``ForeignObject`` subclass, so adopting the safer descriptor does not
        # change the field's deconstruction path and manufacture migrations.
        safe_field.forward_related_accessor_class = OrganizationSafeForwardManyToOneDescriptor
        safe_field.contribute_to_class(cls, name)


class OrganizationSafeForeignKey(OrganizationSafeRelation):
    """A ``ForeignKey`` whose ORM traversals also match on the organization."""

    concrete_field_class = models.ForeignKey


class OrganizationSafeOneToOneField(OrganizationSafeRelation):
    """A ``OneToOneField`` whose ORM traversals also match on the organization."""

    concrete_field_class = models.OneToOneField
    safe_field_class = OrganizationSafeOneToOneObject
    foreign_object_kwargs = {'unique': True}
    default_related_name_suffix = '_instance'


_safe_relations_cache: dict[type[models.Model], list[str]] = {}


def get_organization_safe_relations(model: type[models.Model]) -> list[str]:
    """Return the names of ``model``'s organization-safe relations.

    Recognized by shape rather than by a registry: a non-concrete
    ``ForeignObject`` named ``<name>`` with a concrete ``<name>_fk`` relation
    beside it. Cached per model -- this is read on every instantiation and every
    save of an organization-aware model.
    """
    try:
        return _safe_relations_cache[model]
    except KeyError:
        pass

    names: list[str] = []

    for field in model._meta.get_fields():
        if not isinstance(field, ForeignObject) or isinstance(field, models.ForeignKey):
            continue

        try:
            concrete_field = model._meta.get_field('%s_fk' % field.name)
        except FieldDoesNotExist:
            continue

        if isinstance(concrete_field, models.ForeignKey):
            names.append(field.name)

    _safe_relations_cache[model] = names
    return names


def expand_safe_relation_field_names(model: type[models.Model], field_names: Sequence[str]) -> Sequence[str]:
    """Replace a safe relation's name with the concrete fields behind it.

    ``save(update_fields=['article'])`` and ``bulk_update(objs, ['article'])``
    both name fields to write, and ``article`` is not writable -- the columns
    are ``article_fk`` and ``organization``.

    Both are expanded, not just the key. Assigning ``instance.article`` sets the
    organization too, so writing the key alone would persist half of the change
    and leave the row pointing across organizations -- the exact state these
    relations exist to make impossible. Expanding both makes
    ``save(update_fields=['article'])`` mean the same as a full ``save()``
    restricted to that relation.
    """
    if not field_names:
        return field_names

    safe_relations = get_organization_safe_relations(model)

    if not safe_relations:
        return field_names

    expanded: list[str] = []

    for field_name in field_names:
        if field_name in safe_relations:
            safe_field = model._meta.get_field(field_name)
            if not isinstance(safe_field, ForeignObject):
                raise TypeError('%s.%s must be a ForeignObject' % (model._meta.label, field_name))
            names = [f.name for f in safe_field.local_related_fields]
        else:
            names = [field_name]

        expanded.extend(name for name in names if name not in expanded)

    return expanded


def rewrite_safe_relation_kwargs(
    model: type[models.Model], kwargs: dict[str, Any], rewrite_instances: bool = True
) -> dict[str, Any]:
    """Move keyword arguments naming a safe relation onto its concrete field.

    ``<name>`` is the non-concrete ``ForeignObject``, so ``update(article=…)``
    and ``Model(article_id=…)`` would otherwise fail -- only ``<name>_fk`` and
    ``<name>_fk_id`` can actually be written. Rewriting here keeps the safe
    relation looking like an ordinary foreign key at the call site.

    ``rewrite_instances=False`` leaves a ``<name>=<instance>`` argument alone:
    on ``Model(...)`` Django's own descriptor handles it, and it does so better
    than this rewrite would -- it copies the target's organization onto the new
    row as well as its key.
    """
    if not kwargs:
        return kwargs

    safe_relations = get_organization_safe_relations(model)

    if not safe_relations:
        return kwargs

    rewritten = dict(kwargs)

    for name in safe_relations:
        if rewrite_instances and name in rewritten:
            rewritten['%s_fk' % name] = rewritten.pop(name)

        if '%s_id' % name in rewritten:
            rewritten['%s_fk_id' % name] = rewritten.pop('%s_id' % name)

    return rewritten
