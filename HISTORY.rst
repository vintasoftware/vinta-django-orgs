.. :changelog:

History
-------

0.1.0 (2026-08-11)
++++++++++++++++++

Breaking
~~~~~~~~

* ``OrganizationMembership.objects`` no longer scopes to the selected
  organization (#6). A membership is how an organization gets selected in the
  first place, so scoping it was circular. ``user.memberships``,
  ``organization.memberships`` and ``OrganizationMembership.objects`` now read
  every organization.

  Narrow explicitly where you need one:
  ``user.memberships.for_current_organization()``,
  ``OrganizationMembership.objects.filter_by_organization(org)``, or the
  still-scoped ``OrganizationMembership.organization_objects``.

  **Check your own permission code.** Anything filtering memberships without
  naming an organization -- ``user.memberships.filter(groups__name=...)`` --
  silently widens from "in this organization" to "in any organization". The
  permission classes shipped here were updated and behave exactly as before.

Added
~~~~~

* ``Organization`` and ``OrganizationMembership`` are swappable (#7), the way
  ``auth.User`` is. Subclass ``AbstractOrganization`` /
  ``AbstractOrganizationMembership`` and point the settings at your models:

  .. code:: python

      ORGANIZATION_MODEL = 'tenancy.Organization'
      ORGANIZATION_MEMBERSHIP_MODEL = 'tenancy.OrganizationMembership'

  Both settings default to the models shipped here, so existing projects need
  no changes. Resolve them with ``organizations.conf.get_organization_model()``
  and ``get_organization_membership_model()`` rather than importing the classes.

  Decide before your first migration -- like ``AUTH_USER_MODEL``, swapping after
  tables exist means moving data by hand.

* ``DEFAULT_ORGANIZATION_OWNER_PERMISSIONS`` is derived from the configured
  models instead of hardcoded, so it follows a swap.

Fixed
~~~~~

* ``_base_manager`` no longer routes through the scoped manager (#1). On default
  settings and with no organization selected, re-saving an existing row raised
  ``IntegrityError`` on a duplicate primary key -- the ``UPDATE`` matched
  nothing, so Django fell through to an ``INSERT`` -- and ``refresh_from_db()``
  raised ``DoesNotExist`` for a row that exists. Under
  ``STRICT_ORGANIZATION_FILTER`` it also broke cascade deletes, forward relation
  reads, and saving an instance built with an explicit ``organization=``.

  Which models were affected depended on base-class order, so
  ``class M(SingleOrganizationModelMixin)`` hit it while the library's own models
  did not.

* ``Model.objects.none()`` works with no organization selected (#2). It asks for
  no rows and cannot leak any, but went through the scoping and raised under
  ``STRICT_ORGANIZATION_FILTER`` -- breaking ``return Model.objects.none()`` in
  views and ``manage.py spectacular``.

* ``DEFAULT_ORGANIZATION_SLUG = None`` no longer queries (#3). Saying "no
  catch-all organization" still ran ``WHERE slug IS NULL`` once per saved row
  before raising anyway.

* The example app's membership signal receivers are connected from
  ``AppConfig.ready()`` against the configured model, instead of being bound to
  the shipped class at import time (#7).

Migrations
~~~~~~~~~~

* New migrations in ``organizations`` and ``organizations_custom_data`` record
  the manager and ``Meta`` changes above (#8). They are state-only, touch no
  table, and exist so ``makemigrations --check`` stays clean.

Internal
~~~~~~~~

* The test suite runs twice -- once with the default models, once with both
  swapped -- wired into ``tox``, so every Python/Django matrix cell covers both.
  253 tests, up from 212.

0.0.3 (2026-08-11)
++++++++++++++++++

* First release on PyPI.
