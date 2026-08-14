"""Caching for the organization lookup every request performs.

``retrieve_by_domain`` is the first retriever a request tries, and it costs a
query mapping the site to its organization -- on every request that touches
organization-scoped data. The mapping changes when a domain is reassigned,
which is to say almost never, so it caches well.

It is off by default. A stale entry here does not make a page slow, it serves
one organization's data to another, and that is not a trade to make on someone's
behalf. Two things bound the risk once it is turned on:

* every write to :class:`~vinta_orgs.models.Organization` or
  :class:`~vinta_orgs.models.OrganizationSite` drops the affected entries, and
* entries expire on their own, so a write that bypasses Django -- raw SQL, a
  restore, another service on the same database -- is corrected within
  ``ORGANIZATION_CACHE_TIMEOUT`` rather than never.

The organization is stored as its column values rather than as a pickled model,
so a deploy that adds or removes a field cannot resurrect an instance that no
longer matches the table.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, Literal, TypeAlias

from django.core.cache import caches
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from vinta_orgs.conf import organization_model_string
from vinta_orgs.settings import get_setting

if TYPE_CHECKING:
    from django.core.cache.backends.base import BaseCache

    from vinta_orgs.models import AbstractOrganization

#: Cached in place of an organization when a site maps to none, so an unmapped
#: domain does not re-query on every request either.
NoOrganization: TypeAlias = Literal['__none__']
NO_ORGANIZATION: Final[NoOrganization] = '__none__'

KEY_PREFIX = 'shared-schema-organizations:site'


def is_enabled() -> bool:
    return bool(get_setting('CACHE_ORGANIZATION_RETRIEVAL'))


def get_cache() -> BaseCache:
    return caches[get_setting('ORGANIZATION_CACHE_ALIAS')]


def cache_key(site_id: Any) -> str:
    return '%s:%s' % (KEY_PREFIX, site_id)


def _dump(organization: AbstractOrganization) -> dict[str, Any]:
    return {field.attname: getattr(organization, field.attname) for field in organization._meta.concrete_fields}


def _load(values: dict[str, Any]) -> AbstractOrganization | None:
    from vinta_orgs.conf import get_organization_model

    organization_model = get_organization_model()
    field_names = {field.attname for field in organization_model._meta.concrete_fields}

    # A column list that no longer matches the model means the cache outlived a
    # migration -- or a deploy that swapped ``ORGANIZATION_MODEL`` for one with
    # different columns. Treated as a miss rather than reconstructed
    # half-populated.
    if set(values) != field_names:
        return None

    organization = organization_model(**values)
    organization._state.adding = False
    return organization


def get_cached_organization_for_site(site_id: Any) -> AbstractOrganization | None | NoOrganization:
    """Return the cached organization, ``NO_ORGANIZATION``, or ``None`` for a miss."""
    if not is_enabled():
        return None

    cached = get_cache().get(cache_key(site_id))

    if cached is None or cached == NO_ORGANIZATION:
        return cached

    return _load(cached)


def set_cached_organization_for_site(site_id: Any, organization: AbstractOrganization | None) -> None:
    if not is_enabled():
        return

    value = _dump(organization) if organization is not None else NO_ORGANIZATION
    get_cache().set(cache_key(site_id), value, get_setting('ORGANIZATION_CACHE_TIMEOUT'))


def forget_site(site_id: Any) -> None:
    if not is_enabled():
        return

    get_cache().delete(cache_key(site_id))


@receiver(post_save, sender='vinta_orgs.OrganizationSite')
@receiver(post_delete, sender='vinta_orgs.OrganizationSite')
def _forget_organization_site(sender: Any, instance: Any, **kwargs: Any) -> None:
    forget_site(instance.site_id)


# Connected by name to the *configured* model rather than to the class shipped
# here: a project that swapped ``ORGANIZATION_MODEL`` writes rows of its own
# model, and a receiver bound to this app's would simply never fire.
@receiver(post_save, sender=organization_model_string())
@receiver(post_delete, sender=organization_model_string())
def _forget_organization(sender: Any, instance: Any, **kwargs: Any) -> None:
    """Drop every site that pointed at this organization.

    Costs a query, but only when an organization is written -- which is rare,
    and rarer still than the per-request read this exists to avoid.
    """
    if not is_enabled():
        return

    from vinta_orgs.models import OrganizationSite

    site_ids = OrganizationSite.original_manager.filter(organization=instance).values_list('site_id', flat=True)
    get_cache().delete_many([cache_key(site_id) for site_id in site_ids])
