"""django-tenants with ``TENANT_LIMIT_SET_CALLS`` turned on.

By default django-tenants issues ``SET search_path`` on every cursor, so every
query costs an extra round trip. ``TENANT_LIMIT_SET_CALLS = True`` issues it
once per schema switch instead. Both are benchmarked: the default is what a
project gets without reading the tuning docs, and this is the ceiling the
approach can actually reach.
"""

from benchmarks.config import database
from benchmarks.settings_tenants import *  # noqa: F403

DATABASES = database('tenants_limited', engine='django_tenants.postgresql_backend')

TENANT_LIMIT_SET_CALLS = True
