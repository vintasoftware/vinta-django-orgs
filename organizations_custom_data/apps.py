from django.apps import AppConfig


class OrganizationsCustomDataConfig(AppConfig):
    name = 'organizations_custom_data'
    # Keeps the primary keys already created by 0001_initial, regardless of the
    # DEFAULT_AUTO_FIELD chosen by the project using this app.
    default_auto_field = 'django.db.models.AutoField'
