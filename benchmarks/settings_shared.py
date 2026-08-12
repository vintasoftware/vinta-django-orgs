"""Settings for the ``shared`` approach: this library's row-level scoping."""

from benchmarks.config import database

SECRET_KEY = 'benchmark'
DEBUG = False
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

DATABASES = database('shared')

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'django.contrib.sites',
    'vinta_orgs.apps.OrganizationsConfig',
    'benchmarks.apps.shared_app',
]

SITE_ID = 1
USE_I18N = False
