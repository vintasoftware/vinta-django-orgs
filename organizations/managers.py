from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db.models import Manager, QuerySet

from organizations.querysets import (
    MultipleOrganizationsQuerySet,
    SingleOrganizationQuerySet,
    exclude_queryset_by_organization,
    filter_queryset_by_organization,
    scope_queryset_to_current_organization,
)

if TYPE_CHECKING:
    from organizations.models import Organization

    class _ManagerBase(Manager[Any]):
        """What the mixin needs from the manager it is combined with.

        Declared instead of using ``Manager`` directly because this mixin sits
        in front of managers whose ``get_queryset`` takes extra arguments (see
        ``organizations_custom_data.managers``), which the base signature does
        not describe. Nothing is added at runtime.
        """

        def get_queryset(self, *args: Any, **kwargs: Any) -> QuerySet[Any]: ...
else:
    _ManagerBase = object


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
    ``organizations.querysets``), they keep chaining after any
    other lookup instead of only being reachable as the first call.
    """

    organization_lookup: str = 'organization'

    def get_original_queryset(self, *args: Any, **kwargs: Any) -> QuerySet[Any]:
        """Return the queryset with no organization scoping applied."""
        return super().get_queryset(*args, **kwargs)

    def unscoped(self, *args: Any, **kwargs: Any) -> QuerySet[Any]:
        """Readable alias for :meth:`get_original_queryset`."""
        return self.get_original_queryset(*args, **kwargs)

    def get_queryset(self, organization: Organization | None = None, *args: Any, **kwargs: Any) -> QuerySet[Any]:
        queryset = self.get_original_queryset(*args, **kwargs)

        if organization is None:
            return scope_queryset_to_current_organization(queryset, self.organization_lookup)

        return filter_queryset_by_organization(queryset, organization, self.organization_lookup)

    def filter_by_organization(self, organization: Organization, *args: Any, **kwargs: Any) -> QuerySet[Any]:
        return filter_queryset_by_organization(
            self.get_original_queryset(*args, **kwargs), organization, self.organization_lookup
        )

    def exclude_by_organization(self, organization: Organization, *args: Any, **kwargs: Any) -> QuerySet[Any]:
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
else:
    _SingleOrganizationManagerBase = Manager.from_queryset(SingleOrganizationQuerySet)
    _MultipleOrganizationsManagerBase = Manager.from_queryset(MultipleOrganizationsQuerySet)


class SingleOrganizationModelManager(OrganizationScopedManagerMixin, _SingleOrganizationManagerBase):
    organization_lookup = 'organization'


class MultipleOrganizationModelManager(OrganizationScopedManagerMixin, _MultipleOrganizationsManagerBase):
    organization_lookup = 'organizations'


# Used as ``original_manager`` on the model mixins: no implicit scoping, but the
# same scoping methods, so code that deliberately reads across organizations can
# still narrow down later instead of falling back to raw ``filter()`` calls.
SingleOrganizationUnscopedManager = _SingleOrganizationManagerBase
MultipleOrganizationsUnscopedManager = _MultipleOrganizationsManagerBase
