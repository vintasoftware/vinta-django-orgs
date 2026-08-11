from django.apps import AppConfig


class OrganizationsConfig(AppConfig):
    name = 'organizations'
    # Keeps the primary keys already created by 0001_initial, regardless of the
    # DEFAULT_AUTO_FIELD chosen by the project using this app.
    default_auto_field = 'django.db.models.AutoField'

    def ready(self) -> None:
        # Connects the receivers that drop a cached organization when it or one
        # of its sites is written. Imported here because the only other importer
        # is the retriever, which the middleware loads lazily -- so without this
        # the cache could be filled before anything was listening to invalidate
        # it.
        from organizations import cache  # noqa: F401
