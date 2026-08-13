from django.apps import AppConfig

from vinta_orgs.conf import apply_setting_defaults

# Runs while Django is building the app registry, which imports this module
# before it imports any ``models`` module. That ordering is the point:
# ``Organization`` and ``OrganizationMembership`` read ``ORGANIZATION_MODEL`` and
# ``ORGANIZATION_MEMBERSHIP_MODEL`` at class-definition time, and so does every
# migration that points a foreign key at them, so the settings have to exist by
# then even on a project that never mentioned them.
apply_setting_defaults()


class OrganizationsConfig(AppConfig):
    name = 'vinta_orgs'
    # Keeps the primary keys already created by 0001_initial, regardless of the
    # DEFAULT_AUTO_FIELD chosen by the project using this app.
    default_auto_field = 'django.db.models.AutoField'

    def ready(self) -> None:
        # Connects the receivers that drop a cached organization when it or one
        # of its sites is written. Imported here because the only other importer
        # is the retriever, which the middleware loads lazily -- so without this
        # the cache could be filled before anything was listening to invalidate
        # it.
        from django.core.checks import register

        from vinta_orgs import cache  # noqa: F401
        from vinta_orgs.checks import check_middleware_order

        register(check_middleware_order)
