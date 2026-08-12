"""Chainable organization scoping for querysets.

The scoping used to live only on the managers, which meant it could not be
composed: ``Article.objects.get_queryset(organization=other)`` was the single
entry point and anything already filtered (a related manager, a queryset handed
over by another function, ``Article.objects.filter(...)``) had no way to reach
it. Putting the scoping on the queryset makes it chain like every other Django
lookup::

    Article.objects.filter(published=True).filter_by_organization(other)
    author.article_set.for_current_organization()

The three module-level functions hold the actual behaviour so the managers can
scope a queryset whose class does not inherit
:class:`OrganizationScopedQuerySetMixin` -- a project is free to point
``_queryset_class`` at its own ``QuerySet`` subclass.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Self, TypeVar

from django.db import connections
from django.db.models import Exists, OuterRef, QuerySet, Subquery
from django.db.models.constants import LOOKUP_SEP

from vinta_orgs.exceptions import OrganizationNotFoundError
from vinta_orgs.fields import (
    expand_safe_relation_field_names,
    get_organization_safe_relations,
    rewrite_safe_relation_kwargs,
)
from vinta_orgs.settings import get_setting
from vinta_orgs.state import get_current_organization

if TYPE_CHECKING:
    from django.db.backends.base.base import BaseDatabaseWrapper
    from django.db.models.sql.compiler import SQLCompiler, _AsSqlType

    from vinta_orgs.models import Organization

#: Preserves the caller's queryset class through a scoping call, so a project
#: that points ``_queryset_class`` at its own subclass keeps its own methods.
_QuerySetT = TypeVar('_QuerySetT', bound=QuerySet[Any])


def filter_queryset_by_organization(
    queryset: _QuerySetT, organization: Organization, organization_lookup: str = 'organization'
) -> _QuerySetT:
    """Restrict ``queryset`` to ``organization``."""
    return queryset.filter(**{organization_lookup: organization})


def exclude_queryset_by_organization(
    queryset: _QuerySetT, organization: Organization, organization_lookup: str = 'organization'
) -> _QuerySetT:
    """Drop every row of ``queryset`` belonging to ``organization``."""
    return queryset.exclude(**{organization_lookup: organization})


def scope_queryset_to_current_organization(
    queryset: _QuerySetT, organization_lookup: str = 'organization'
) -> _QuerySetT:
    """Restrict ``queryset`` to the organization bound to the current context.

    With no organization bound this returns an empty queryset, so a query that
    escapes its scope can never leak another organization's rows. Set
    ``STRICT_ORGANIZATION_FILTER`` to raise ``OrganizationNotFoundError``
    instead -- silently empty results are hard to tell from "no data yet" in a
    task or a management command, where forgetting to bind an organization is
    the likelier explanation.
    """
    organization = get_current_organization()

    if not organization:
        if get_setting('STRICT_ORGANIZATION_FILTER'):
            raise OrganizationNotFoundError(
                'No organization is bound to the current context, so %s cannot be '
                'queried. Bind one with `organization_context(...)`, scope the query '
                'explicitly with `filter_by_organization(...)`, or read every '
                'organization through `original_manager`.' % queryset.model.__name__
            )

        return queryset.none()

    return filter_queryset_by_organization(queryset, organization, organization_lookup)


if TYPE_CHECKING:
    # The mixin is only ever combined with a ``QuerySet``, and its methods rely
    # on that. Saying so to the type checker without adding the base at runtime
    # keeps the MRO of every subclass exactly as it is.
    _QuerySetBase = QuerySet[Any]
else:
    _QuerySetBase = object


class OrganizationScopedQuerySetMixin(_QuerySetBase):
    """Scoping methods shared by the single- and multiple-organization querysets.

    Subclasses only have to point ``organization_lookup`` at the field that
    relates the model to ``Organization``.
    """

    organization_lookup: str = 'organization'

    def filter_by_organization(self, organization: Organization) -> Self:
        """Restrict the queryset to ``organization``."""
        return filter_queryset_by_organization(self, organization, self.organization_lookup)

    def exclude_by_organization(self, organization: Organization) -> Self:
        """Drop every row belonging to ``organization``."""
        return exclude_queryset_by_organization(self, organization, self.organization_lookup)

    def for_current_organization(self) -> Self:
        """Restrict the queryset to the organization bound to the current context."""
        return scope_queryset_to_current_organization(self, self.organization_lookup)


def _prefetch_paths(name: str, nested: dict[str, Any]) -> list[str]:
    """Turn one ``select_related`` entry into the ``prefetch_related`` lookups for it.

    ``{'article': {'author': {}}}`` becomes ``['article__author']``: prefetching
    the deeper path walks the shallower one on its way, so naming the leaves is
    enough.
    """
    if not nested:
        return [name]

    paths: list[str] = []

    for child, grandchildren in nested.items():
        paths.extend('%s__%s' % (name, path) for path in _prefetch_paths(child, grandchildren))

    return paths


class FencedExists(Exists):
    """``EXISTS`` that PostgreSQL evaluates per row instead of folding into a join.

    ``OFFSET 0`` is a no-op that PostgreSQL nonetheless treats as an
    optimization fence: it stops the subquery being pulled up, which is the
    only thing that persuades the planner to walk the outer rows in index order
    and stop at the end of the page. Everything else -- ``Exists`` on its own,
    ``pk__in`` with a subquery, a semi-join on the key -- is normalized back
    into the same hash join.

    The fence is only applied on PostgreSQL. It is where the behaviour was
    measured, and elsewhere ``OFFSET`` without ``LIMIT`` is either meaningless
    or a syntax error, so other backends get a plain ``EXISTS``.
    """

    def as_sql(
        self,
        compiler: SQLCompiler,
        connection: BaseDatabaseWrapper,
        template: str | None = None,
        **extra_context: Any,
    ) -> _AsSqlType:
        sql, params = super().as_sql(compiler, connection, template, **extra_context)

        # Guarded rather than assumed: if a future Django wraps ``EXISTS`` in
        # something else, this drops back to the unfenced form -- a slower
        # plan, not a broken query.
        if connection.vendor == 'postgresql' and sql.endswith(')'):
            sql = '%s OFFSET 0)' % sql[:-1]

        return sql, params


class SingleOrganizationQuerySet(OrganizationScopedQuerySetMixin, QuerySet):
    """Queryset for models with an ``organization`` foreign key."""

    organization_lookup = 'organization'

    def _related_exists_subquery(self, relation: str, conditions: dict[str, Any]) -> QuerySet[Any]:
        """Correlate ``relation``'s target back to the outer row, on key and organization.

        The same two columns the organization-safe relation puts in its ``ON``
        clause, so this matches exactly the rows the join would have matched --
        including when the outer queryset is unscoped.
        """
        concrete = self.model._meta.get_field('%s_fk' % relation)
        target = self.model._meta.get_field(relation).related_model
        manager = getattr(target, 'original_manager', target._default_manager)

        return manager.filter(
            pk=OuterRef(concrete.attname),
            organization=OuterRef('organization'),
            **conditions,
        )

    def filter_related_without_join(self, **lookups: Any) -> Self:
        """Filter on an organization-safe relation by checking each row, not by joining.

        The ordinary ``filter(article__status='published')`` joins, and that
        join matches on the organization as well as on the key -- which
        PostgreSQL costs as if the two conditions were independent, so it
        underestimates the join and stops using the ordered index. Under a
        ``LIMIT`` that means building the whole join and sorting it to return a
        page::

            Comment.objects.filter_related_without_join(article__status='published')[:50]

        **This is a trade, not a free win, and which way it goes depends on how
        many rows match.** Measured on 25 organizations of 3,000 articles, a
        page of 50:

        =========================  ======  =======
        Filter matches             join    this
        =========================  ======  =======
        1 in 3 articles            1.854   0.382
        ~1 in 100                  0.508   0.306
        ~1 in 1000                 0.507   6.345
        nothing                    0.668   6.579
        =========================  ======  =======

        The page is filled by walking the organization's rows in primary key
        order and testing each one, so it is fast when matches are common and
        slow when they are rare -- with nothing to find, it walks everything the
        organization owns. PostgreSQL's join is the safer default precisely
        because it bounds that case; reach for this when you know the filter is
        not selective.

        Rows are matched exactly as the safe relation would match them: a row
        pointing at another organization's target does not match.
        """
        safe_relations = set(get_organization_safe_relations(self.model))
        grouped: dict[str, dict[str, Any]] = {}

        for lookup, value in lookups.items():
            relation, _, remainder = lookup.partition(LOOKUP_SEP)

            if relation not in safe_relations:
                raise ValueError(
                    '%r is not an organization-safe relation on %s. Only relations declared with '
                    'OrganizationSafeForeignKey or OrganizationSafeOneToOneField join on the '
                    'organization, so only they have anything to gain here -- filter() the rest.'
                    % (relation, self.model.__name__)
                )

            if not remainder:
                raise ValueError(
                    'filter_related_without_join() needs a lookup *across* %r, such as '
                    '%s__status=..., not the relation on its own.' % (relation, relation)
                )

            grouped.setdefault(relation, {})[remainder] = value

        queryset = self

        for relation, conditions in grouped.items():
            # One ``EXISTS`` per relation rather than per lookup: the conditions
            # describe the same target row, so testing them together is one
            # subquery instead of several.
            queryset = queryset.filter(FencedExists(self._related_exists_subquery(relation, conditions)))

        return queryset

    def _safe_relations_to_defer(self) -> list[str]:
        """The ``select_related`` entries this query is better off not joining.

        Only paged queries qualify. An organization-safe relation joins on the
        organization as well as on the key, and PostgreSQL costs those two
        conditions as though they were independent -- so the more organizations
        exist, the further it underestimates the join, until it abandons the
        ordered index walk for a hash join it has to sort. Splitting the read in
        two hands it a page of rows instead of an estimate, which no amount of
        indexing does. Unpaged reads are unaffected by the misestimate and are
        left alone.
        """
        if self.query.high_mark is None:
            return []

        select_related = self.query.select_related

        # ``select_related()`` with no arguments is ``True`` here and is
        # expanded at compile time. Rewriting that would change *which*
        # relations are followed rather than only how they are fetched.
        if not isinstance(select_related, dict):
            return []

        if not get_setting('AUTO_DEFER_SAFE_JOINS'):
            return []

        safe_relations = set(get_organization_safe_relations(self.model))

        return [name for name in select_related if name in safe_relations]

    def _paged_by_subquery(self) -> QuerySet[Any]:
        """The same page, with the ``LIMIT`` applied before the join instead of after.

        ``WHERE pk IN (SELECT pk … ORDER BY … LIMIT n)`` walks the
        ``(organization, pk)`` index to collect the page, then joins those rows
        and only those. The planner never has to guess how many rows the join
        will produce, which is the estimate it gets wrong by roughly the number
        of organizations.
        """
        # ``self`` still carries the slice, so the inner query is the page.
        inner = self.values('pk')

        outer = self.all()
        outer.query.clear_limits()

        return outer.filter(pk__in=Subquery(inner))

    def _fetch_all(self) -> None:
        if self._result_cache is None:
            deferred = self._safe_relations_to_defer()
            select_related = self.query.select_related

            # ``_safe_relations_to_defer`` only returns names when this is a
            # dict; repeating the check keeps that provable here.
            if deferred and isinstance(select_related, dict):
                if connections[self.db].features.allow_sliced_subqueries_with_in:
                    # Keeps the join, but hands it a page of primary keys
                    # instead of an estimate -- and stays one query, so nobody's
                    # query counts change.
                    self._result_cache = list(self._paged_by_subquery())
                    self._prefetch_done = True
                    return

                # MySQL cannot put a sliced subquery inside ``IN``, so there the
                # related rows are fetched separately instead.
                # ``all()`` is ``_chain()`` with a public name on it.
                clone = self.all()
                remaining = {name: nested for name, nested in select_related.items() if name not in deferred}
                clone.query.select_related = remaining or False
                lookups = [path for name in deferred for path in _prefetch_paths(name, select_related[name])]

                # The clone has no safe relation left in ``select_related``, so
                # its own ``_fetch_all`` takes the ordinary path rather than
                # recursing, and it runs the prefetching for both these lookups
                # and any the caller had already asked for.
                self._result_cache = list(clone.prefetch_related(*lookups))
                self._prefetch_done = True
                return

        super()._fetch_all()

    def update(self, **kwargs: Any) -> int:
        # ``update(article=…)`` names the non-concrete half of an
        # organization-safe relation, which Django refuses to write. Point it at
        # the concrete ``article_fk`` instead so the call site does not have to
        # know the relation is split in two.
        #
        # Only the key is written, never ``organization``: this updates rows in
        # bulk with no instance to take a consistent organization from, and
        # writing it would silently move every matched row into the target's
        # organization. The target is expected to be in the same organization
        # already; if it is not, the rows read as missing through the relation
        # rather than as another organization's data.
        return super().update(**rewrite_safe_relation_kwargs(self.model, kwargs))

    def bulk_update(self, objs: Iterable[Any], fields: Iterable[str], *args: Any, **kwargs: Any) -> int:
        # Unlike ``update()`` above, each object carries its own consistent
        # values, so a safe relation expands to both of its fields.
        #
        # ``list(fields)`` because the expansion walks the names twice and the
        # signature Django documents accepts any iterable, including a generator.
        return super().bulk_update(objs, expand_safe_relation_field_names(self.model, list(fields)), *args, **kwargs)

    def with_organization(self) -> Self:
        """Fetch each row's organization in the same query.

        Anything that reads ``instance.organization`` while iterating -- a
        serializer, a template, ``__str__`` -- otherwise pays one query per row.
        """
        return self.select_related('organization')


class MultipleOrganizationsQuerySet(OrganizationScopedQuerySetMixin, QuerySet):
    """Queryset for models with an ``organizations`` many-to-many relation."""

    organization_lookup = 'organizations'

    def with_organizations(self) -> Self:
        """Fetch every row's organizations in one extra query instead of one per row."""
        return self.prefetch_related('organizations')
