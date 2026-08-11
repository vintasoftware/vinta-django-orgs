"""Settings for the ``manual`` approach: a hand-written tenant column.

No library at all -- the same shared-schema shape, filtered by an explicit
``tenant_id`` at every call site. This is the control: the gap between it and
``shared`` is what the library's machinery costs, and the gap between it and
``tenants`` is what row-level scoping costs regardless of library.
"""

from benchmarks.config import database

SECRET_KEY = 'benchmark'
DEBUG = False
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

DATABASES = database('manual')

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'benchmarks.apps.manual_app',
]

USE_I18N = False
