from __future__ import annotations

import contextlib
from collections.abc import Iterator, Mapping
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from django.db.models import Manager, QuerySet

from vinta_orgs.querysets import (
    MultipleOrganizationsQuerySet,
    OrganizationMembershipQuerySet,
    SingleOrganizationQuerySet,
    exclude_queryset_by_organization,
    filter_queryset_by_organization,
    scope_queryset_to_current_organization,
)

if TYPE_CHECKING:
    from vinta_orgs.models import AbstractOrganization

    class _ManagerBase(Manager[Any]):
        """What the mixin needs from the manager it is combined with.

        Declared instead of using ``Manager`` directly because this mixin sits
        in front of managers whose ``get_queryset`` takes extra arguments (see
        ``vinta_orgs_custom_data.managers``), which the base signature does
        not describe. Nothing is added at runtime.
        """

        def get_queryset(self, *args: Any, **kwargs: Any) -> QuerySet[Any]: ...
else:
    _ManagerBase = object


_default_manager_is_unscoped: ContextVar[bool] = ContextVar('vinta_orgs.default_manager_is_unscoped', default=False)


@contextlib.contextmanager
def unscoped_default_manager() -> Iterator[None]:
    """Temporarily make every scoped default manager return its original queryset.

    This is intentionally process-wide in meaning but context-local in storage.
    Keep its scope to a Django internal call that offers no queryset override,
    such as ``ForeignKey.formfield()``.
    """
    token = _default_manager_is_unscoped.set(True)
    try:
        yield
    finally:
        _default_manager_is_unscoped.reset(token)


class OrganizationScopedManagerMixin(_ManagerBase):
    """Manager behaviour shared by the single- and multiple-organization managers.

    ``get_queryset()`` scopes to the organization bound to the current context,
    which is what makes ``MyModel.objects`` safe by default. Everything that
    needs to step outside that scope says so explicitly:

    * ``filter_by_organization(org)`` / ``exclude_by_organization(org)`` start
      from the *unscoped* queryset, so they mean what they say even when another
      organization is bound -- reaching for another organization's rows is the
      whole reason to call them.
    * ``unscoped()`` returns every row, for reports and migrations.

    Because these live on the queryset too (see
    ``vinta_orgs.querysets``), they keep chaining after any
    other lookup instead of only being reachable as the first call.
    """

    organization_lookup: str = 'organization'

    def get_original_queryset(self, *args: Any, **kwargs: Any) -> QuerySet[Any]:
        """Return the queryset with no organization scoping applied."""
        return super().get_queryset(*args, **kwargs)

    def unscoped(self, *args: Any, **kwargs: Any) -> QuerySet[Any]:
        """Readable alias for :meth:`get_original_queryset`."""
        return self.get_original_queryset(*args, **kwargs)

    def get_queryset(
        self, organization: AbstractOrganization | None = None, *args: Any, **kwargs: Any
    ) -> QuerySet[Any]:
        queryset = self.get_original_queryset(*args, **kwargs)

        # Django-generated reverse and many-to-many managers carry the source
        # instance and add their relation filter after this method returns. That
        # filter is the authority for an explicit instance traversal; demanding
        # an unrelated ambient organization makes reverse access and prefetches
        # unusable outside a request.
        if getattr(self, 'instance', None) is not None or _default_manager_is_unscoped.get():
            return queryset

        if organization is None:
            return scope_queryset_to_current_organization(queryset, self.organization_lookup)

        return filter_queryset_by_organization(queryset, organization, self.organization_lookup)

    def create(self, **kwargs: Any) -> Any:
        """Insert one row, with no organization needing to be bound.

        ``Manager.create`` is generated as ``self.get_queryset().create(...)``,
        so under ``STRICT_ORGANIZATION_FILTER`` it used to raise
        ``OrganizationNotFoundError`` -- for a statement that reads no rows at
        all and therefore cannot read another organization's. It broke
        ``MyModel.objects.create(organization=organization)``, which names its
        organization outright, and every ``instance.related_set.create(...)``,
        which Django routes through this same method.

        Without the strict setting the scoping was merely pointless here:
        ``none()`` marks a query as returning nothing on *select*, and the
        ``INSERT`` went ahead regardless.

        Built from the unscoped queryset instead. Nothing about which
        organization the row lands in changes -- ``save()`` still takes the
        explicit ``organization=``, then the bound one, then
        ``DEFAULT_ORGANIZATION_SLUG``, and still raises
        ``OrganizationNotFoundError`` when none of the three produced one. Only
        the point at which an unbound caller finds out moves, from the query to
        the write.
        """
        return self.get_original_queryset().create(**kwargs)

    async def acreate(self, **kwargs: Any) -> Any:
        return await self.get_original_queryset().acreate(**kwargs)

    def bulk_create(self, objs: Any, *args: Any, **kwargs: Any) -> Any:
        """The same, for many rows at once, and for the same reason.

        Unlike :meth:`create` this does not go through ``save()``, so each
        object must already carry its organization -- which was true before this
        method existed and is not changed by it.
        """
        return self.get_original_queryset().bulk_create(objs, *args, **kwargs)

    async def abulk_create(self, objs: Any, *args: Any, **kwargs: Any) -> Any:
        return await self.get_original_queryset().abulk_create(objs, *args, **kwargs)

    @staticmethod
    def _names_an_organization(kwargs: dict[str, Any] | None) -> bool:
        if not kwargs:
            return False
        return any(kwargs.get(name) is not None for name in ('organization', 'organization_id'))

    def get_or_create(self, defaults: Mapping[str, Any] | None = None, **kwargs: Any) -> Any:
        # Defaults do not constrain the lookup and therefore cannot authorize
        # widening it across organizations.
        queryset = self.get_original_queryset() if self._names_an_organization(kwargs) else self.get_queryset()
        return queryset.get_or_create(defaults=defaults, **kwargs)

    async def aget_or_create(self, defaults: Mapping[str, Any] | None = None, **kwargs: Any) -> Any:
        queryset = self.get_original_queryset() if self._names_an_organization(kwargs) else self.get_queryset()
        return await queryset.aget_or_create(defaults=defaults, **kwargs)

    def update_or_create(
        self,
        defaults: Mapping[str, Any] | None = None,
        create_defaults: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        unsafe_organization_update = kwargs.pop('unsafe_organization_update', False)
        queryset = self.get_original_queryset() if self._names_an_organization(kwargs) else self.get_queryset()
        return queryset.update_or_create(
            defaults=defaults,
            create_defaults=create_defaults,
            unsafe_organization_update=unsafe_organization_update,
            **kwargs,
        )

    async def aupdate_or_create(
        self,
        defaults: Mapping[str, Any] | None = None,
        create_defaults: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        unsafe_organization_update = kwargs.pop('unsafe_organization_update', False)
        queryset = self.get_original_queryset() if self._names_an_organization(kwargs) else self.get_queryset()
        return await queryset.aupdate_or_create(
            defaults=defaults,
            create_defaults=create_defaults,
            unsafe_organization_update=unsafe_organization_update,
            **kwargs,
        )

    def bulk_update(self, objs: Any, fields: Any, *args: Any, **kwargs: Any) -> Any:
        return self.get_original_queryset().bulk_update(objs, fields, *args, **kwargs)

    async def abulk_update(self, objs: Any, fields: Any, *args: Any, **kwargs: Any) -> Any:
        return await self.get_original_queryset().abulk_update(objs, fields, *args, **kwargs)

    def none(self, *args: Any, **kwargs: Any) -> QuerySet[Any]:
        """An empty queryset, with no organization needing to be selected.

        ``Manager.none()`` is generated by ``Manager.from_queryset`` as
        ``self.get_queryset().none()``, so under ``STRICT_ORGANIZATION_FILTER``
        it used to raise ``OrganizationNotFoundError`` -- for a call that asks
        for no rows at all and therefore cannot leak any.

        That refusal broke two ordinary things: ``return MyModel.objects.none()``
        is how a DRF view expresses a read the caller is not allowed to make,
        and introspection asks a model for an empty queryset outside any request
        (drf-spectacular's django-filter integration calls
        ``Model.objects.none()`` while generating the schema, with no
        organization in sight).

        Built from the unscoped queryset instead. The result is empty either
        way; only the path there differs.
        """
        return self.get_original_queryset(*args, **kwargs).none()

    def filter_by_organization(self, organization: AbstractOrganization, *args: Any, **kwargs: Any) -> QuerySet[Any]:
        return filter_queryset_by_organization(
            self.get_original_queryset(*args, **kwargs), organization, self.organization_lookup
        )

    def exclude_by_organization(self, organization: AbstractOrganization, *args: Any, **kwargs: Any) -> QuerySet[Any]:
        return exclude_queryset_by_organization(
            self.get_original_queryset(*args, **kwargs), organization, self.organization_lookup
        )


# ``Manager.from_queryset`` builds its class at runtime, which a type checker
# cannot follow. Spelling the result out as "a manager that also exposes the
# queryset's methods" describes exactly what it produces, so callers get
# ``filter_by_organization``, ``with_organization`` and the rest checked instead
# of falling back to ``Any``.
if TYPE_CHECKING:

    class _SingleOrganizationManagerBase(Manager[Any]):
        """What ``Manager.from_queryset(SingleOrganizationQuerySet)`` produces.

        Only the methods ``Manager`` does not already have are listed -- the
        rest it copies over mean the same thing on both sides.
        """

        def for_current_organization(self) -> SingleOrganizationQuerySet: ...
        def with_organization(self) -> SingleOrganizationQuerySet: ...
        def filter_related_without_join(self, **lookups: Any) -> SingleOrganizationQuerySet: ...

    class _MultipleOrganizationsManagerBase(Manager[Any]):
        """What ``Manager.from_queryset(MultipleOrganizationsQuerySet)`` produces."""

        def for_current_organization(self) -> MultipleOrganizationsQuerySet: ...
        def with_organizations(self) -> MultipleOrganizationsQuerySet: ...

    class _OrganizationMembershipManagerBase(_SingleOrganizationManagerBase):
        """What ``Manager.from_queryset(OrganizationMembershipQuerySet)`` produces."""

        def active(self) -> OrganizationMembershipQuerySet: ...
        def active_for_user(self, user: Any) -> OrganizationMembershipQuerySet: ...
        def holding_permission(self, permission: str) -> OrganizationMembershipQuerySet: ...
else:
    _SingleOrganizationManagerBase = Manager.from_queryset(SingleOrganizationQuerySet)
    _MultipleOrganizationsManagerBase = Manager.from_queryset(MultipleOrganizationsQuerySet)
    _OrganizationMembershipManagerBase = Manager.from_queryset(OrganizationMembershipQuerySet)


class SingleOrganizationModelManager(OrganizationScopedManagerMixin, _SingleOrganizationManagerBase):
    organization_lookup = 'organization'


class MultipleOrganizationModelManager(OrganizationScopedManagerMixin, _MultipleOrganizationsManagerBase):
    organization_lookup = 'organizations'


# Used as ``original_manager`` on the model mixins: no implicit scoping, but the
# same scoping methods, so code that deliberately reads across organizations can
# still narrow down later instead of falling back to raw ``filter()`` calls.
SingleOrganizationUnscopedManager = _SingleOrganizationManagerBase
MultipleOrganizationsUnscopedManager = _MultipleOrganizationsManagerBase

# The membership model's default manager. Unscoped for the reason spelled out on
# ``AbstractOrganizationMembership.objects``, and a strict superset of
# ``SingleOrganizationUnscopedManager`` -- it only adds the membership-shaped
# lookups, so the reverse accessors Django builds from it (``user.memberships``,
# ``organization.memberships``) gain ``active()`` and ``holding_permission()``
# without losing anything they had.
OrganizationMembershipUnscopedManager = _OrganizationMembershipManagerBase
