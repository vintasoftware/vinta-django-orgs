"""The test settings, with both swappable models pointed at a project's own.

The whole suite runs twice: once against ``tests.settings``, where
``ORGANIZATION_MODEL`` and ``ORGANIZATION_MEMBERSHIP_MODEL`` keep their defaults,
and once against this module. Everything the library does -- scoping, retrievers,
the permission backend, the admin, the cache -- has to work either way, and the
only way to know it does is to run it.

``exampleproject.customorgs`` holds the replacement models.
"""

from tests.settings import *  # noqa: F403

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sites',
    'django.contrib.sessions',
    'django.contrib.messages',
    'rest_framework',
    'organizations.apps.OrganizationsConfig',
    # Listed before the apps whose foreign keys point at it. Not strictly
    # required -- migrations carry the dependency -- but it keeps the ordering
    # obvious.
    'exampleproject.customorgs.apps.CustomOrgsConfig',
    'exampleproject.articles',
    'exampleproject.lectures',
    'organizations_custom_data.apps.OrganizationsCustomDataConfig',
]

ORGANIZATION_MODEL = 'customorgs.Organization'
ORGANIZATION_MEMBERSHIP_MODEL = 'customorgs.OrganizationMembership'
