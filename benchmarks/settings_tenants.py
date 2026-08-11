"""Settings for the ``tenants`` approach: django-tenants, one schema per tenant."""

from benchmarks.config import database

SECRET_KEY = 'benchmark'
DEBUG = False
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

DATABASES = database('tenants', engine='django_tenants.postgresql_backend')
DATABASE_ROUTERS = ('django_tenants.routers.TenantSyncRouter',)

SHARED_APPS = [
    'django_tenants',
    'benchmarks.apps.tenants_public',
    'django.contrib.contenttypes',
]

TENANT_APPS = [
    'django.contrib.contenttypes',
    'benchmarks.apps.tenant_app',
]

INSTALLED_APPS = SHARED_APPS + [app for app in TENANT_APPS if app not in SHARED_APPS]

TENANT_MODEL = 'tenants_public.Client'
TENANT_DOMAIN_MODEL = 'tenants_public.Domain'
PUBLIC_SCHEMA_NAME = 'public'

USE_I18N = False
