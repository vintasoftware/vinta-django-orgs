from typing import Any

from django.conf import settings
from django.core.signals import setting_changed
from django.db.models import Model
from django.dispatch import receiver

# ``get_setting`` is called from every manager that scopes a queryset and from
# the middleware on every request, so the resolved dictionary is built once and
# reused instead of being rebuilt per call.
_settings_cache: dict[str, Any] | None = None


def _default_organization_owner_permissions() -> list[str]:
    """The add/change/delete permissions for the three models an owner administers.

    Derived from the models rather than spelled out, because two of them are
    swappable: a project that pointed ``ORGANIZATION_MODEL`` at
    ``tenancy.Organization`` needs ``tenancy.change_organization``, and a
    hardcoded ``organizations.change_organization`` names a permission that
    Django never created for it. The owner group was then built with nothing in
    it, and every ``DjangoModelPermissions`` check on the organization endpoints
    returned 403.
    """
    from organizations.conf import get_organization_membership_model, get_organization_model
    from organizations.models import OrganizationSite

    # Annotated: the three have no common base narrower than ``Model``, so
    # inference otherwise lands on ``object``.
    models: list[type[Model]] = [get_organization_model(), get_organization_membership_model(), OrganizationSite]

    return [
        '%s.%s_%s' % (model._meta.app_label, action, model._meta.model_name)
        for model in models
        for action in ('add', 'change', 'delete')
    ]


def _build_settings() -> dict[str, Any]:
    organization_settings = getattr(settings, 'SHARED_SCHEMA_ORGANIZATIONS', {})
    serializers = organization_settings.get('SERIALIZERS', {})

    # Resolved here rather than inline below so that a project which configured
    # its own list never touches the app registry -- and so that an explicitly
    # empty list stays empty instead of falling back to the derived one.
    owner_permissions = organization_settings.get('DEFAULT_ORGANIZATION_OWNER_PERMISSIONS')
    if owner_permissions is None:
        owner_permissions = _default_organization_owner_permissions()

    return {
        'ORGANIZATION_SERIALIZER': serializers.get(
            'ORGANIZATION_SERIALIZER', 'organizations.serializers.OrganizationSerializer'
        ),
        'ORGANIZATION_SITE_SERIALIZER': serializers.get(
            'ORGANIZATION_SITE_SERIALIZER', 'organizations.serializers.OrganizationSiteSerializer'
        ),
        # No membership serializer ships with the library, so this is ``None``
        # unless the project configures one. It used to read the
        # ``ORGANIZATION_SITE_SERIALIZER`` key, which meant a configured
        # membership serializer was silently ignored.
        'ORGANIZATION_MEMBERSHIP_SERIALIZER': serializers.get('ORGANIZATION_MEMBERSHIP_SERIALIZER', None),
        'DEFAULT_SITE_DOMAIN': organization_settings.get('DEFAULT_SITE_DOMAIN', 'localhost'),
        'DEFAULT_ORGANIZATION_SLUG': organization_settings.get('DEFAULT_ORGANIZATION_SLUG', 'default'),
        'ORGANIZATION_RETRIEVERS': organization_settings.get(
            'ORGANIZATION_RETRIEVERS',
            [
                'organizations.organization_retrievers.retrieve_by_domain',
                'organizations.organization_retrievers.retrieve_by_http_header',
                'organizations.organization_retrievers.retrieve_by_session',
            ],
        ),
        'ADD_ORGANIZATION_TO_SESSION': organization_settings.get('ADD_ORGANIZATION_TO_SESSION', True),
        'ORGANIZATION_HTTP_HEADER': organization_settings.get('ORGANIZATION_HTTP_HEADER', 'Organization-Slug'),
        # When True, querying an organization-scoped model with no organization
        # bound raises ``OrganizationNotFoundError`` instead of returning an
        # empty queryset. Off by default because an unscoped read is harmless
        # (it returns nothing); turn it on to catch the tasks and commands that
        # forgot to bind an organization instead of having them report "no data".
        'STRICT_ORGANIZATION_FILTER': organization_settings.get('STRICT_ORGANIZATION_FILTER', False),
        # When True, a paged query that ``select_related`` an
        # organization-safe relation fetches the related rows in a second query
        # instead of joining. The join matches on the organization as well as
        # on the key, and PostgreSQL costs the two conditions as if they were
        # independent -- they are not -- so it underestimates the join by
        # roughly the number of organizations and stops using the index that
        # would have let it stop at the end of the page. See
        # ``benchmarks/RESULTS.md``. Turn it off to keep one query per read at
        # the cost of a join whose plan degrades as organizations are added.
        'AUTO_DEFER_SAFE_JOINS': organization_settings.get('AUTO_DEFER_SAFE_JOINS', True),
        # Caches the site -> organization mapping ``retrieve_by_domain`` looks
        # up, which is one query on every request that reads scoped data. Off by
        # default: a stale entry here serves one organization's data to another,
        # so it is opt-in even though writes invalidate it. See
        # ``organizations.cache``.
        'CACHE_ORGANIZATION_RETRIEVAL': organization_settings.get('CACHE_ORGANIZATION_RETRIEVAL', False),
        'ORGANIZATION_CACHE_ALIAS': organization_settings.get('ORGANIZATION_CACHE_ALIAS', 'default'),
        # Bounds how long a write that bypassed Django can go uncorrected.
        'ORGANIZATION_CACHE_TIMEOUT': organization_settings.get('ORGANIZATION_CACHE_TIMEOUT', 300),
        'DEFAULT_ORGANIZATION_OWNER_PERMISSIONS': owner_permissions,
    }


def get_setting(settings_name: str) -> Any:
    """Return the resolved value of ``settings_name``, or ``None`` if unknown.

    The return type is deliberately ``Any``: the settings dictionary is
    heterogeneous (strings, booleans, lists of import paths), and the callers
    each know which one they asked for.
    """
    global _settings_cache

    if _settings_cache is None:
        _settings_cache = _build_settings()

    return _settings_cache.get(settings_name)


@receiver(setting_changed)
def _reset_settings_cache(sender: Any, setting: str, **kwargs: Any) -> None:
    """Drop the cache when ``override_settings`` touches our configuration."""
    if setting == 'SHARED_SCHEMA_ORGANIZATIONS':
        global _settings_cache
        _settings_cache = None
