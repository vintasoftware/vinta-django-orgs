from typing import Any

from django.conf import settings


def get_setting(settings_name: str) -> Any:
    """Return the resolved value of ``settings_name``, or ``None`` if unknown.

    ``Any`` because the settings are heterogeneous -- lists of model labels,
    lists of permission import paths, separator strings -- and each caller
    knows which one it asked for.
    """
    app_settings = getattr(settings, 'SHARED_SCHEMA_ORGANIZATIONS_CUSTOM_DATA', {})
    settings_dict: dict[str, Any] = {
        'CUSTOMIZABLE_MODELS': app_settings.get('CUSTOMIZABLE_MODELS', []),
        'CUSTOM_TABLES_FILTER_KEYWORD': app_settings.get('CUSTOM_TABLES_FILTER_KEYWORD', '_custom_tables'),
        'CUSTOM_TABLES_LABEL': app_settings.get('CUSTOM_TABLES_LABEL', '_custom_tables'),
        'CUSTOMIZABLE_MODELS_LIST_CREATE_PERMISSIONS': app_settings.get(
            'CUSTOMIZABLE_MODELS_LIST_CREATE_PERMISSIONS', ['vinta_orgs.permissions.IsOrganizationOwner']
        ),
        'CUSTOMIZABLE_MODELS_RETRIEVE_UTPADE_DESTROY_PERMISSIONS': app_settings.get(
            'CUSTOMIZABLE_MODELS_RETRIEVE_UTPADE_DESTROY_PERMISSIONS',
            ['vinta_orgs.permissions.IsOrganizationOwner'],
        ),
        'CUSTOMIZABLE_TABLES_LABEL_SEPARATOR': app_settings.get('CUSTOMIZABLE_TABLES_LABEL_SEPARATOR', '__'),
    }

    return settings_dict.get(settings_name)
