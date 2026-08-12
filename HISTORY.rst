.. :changelog:

History
-------

0.2.0 (2026-08-12)
++++++++++++++++++

Breaking
~~~~~~~~

* Both apps are renamed: ``organizations`` is now ``vinta_orgs``, and
  ``organizations_custom_data`` is now ``vinta_orgs_custom_data``. The old names
  are ordinary enough that a project is likely to want them for an app of its
  own, and two apps cannot share a label. Nothing is kept under the old names:
  update ``INSTALLED_APPS`` (``vinta_orgs.apps.OrganizationsConfig``,
  ``vinta_orgs_custom_data.apps.OrganizationsCustomDataConfig``), the middleware
  and authentication backend paths, every import, the URL namespaces
  (``vinta_orgs:organization_list`` and friends), permission strings such as
  ``vinta_orgs.change_organization``, and ``ORGANIZATION_MODEL`` /
  ``ORGANIZATION_MEMBERSHIP_MODEL`` if they pointed at the shipped models
  (``vinta_orgs.Organization``, ``vinta_orgs.OrganizationMembership``).

Migrations
~~~~~~~~~~

* Each app's migrations are collapsed into a single ``0001_initial`` under its
  new label. The label is what names the tables, so they are created as
  ``vinta_orgs_organization``, ``vinta_orgs_custom_data_...`` and so on rather
  than ``organizations_*``. Nothing migrates the old tables across -- 0.1.1 was
  on PyPI for a day and this is a rename, not a data change -- so a project that
  installed it drops those tables and migrates from scratch.

0.1.1 (2026-08-11)
++++++++++++++++++

No library changes. 0.1.0 was tagged and released on GitHub but never uploaded
to PyPI, so 0.1.1 is what carries the 0.1.0 entries below to PyPI -- upgrading
from 0.0.3 means reading those. Nothing in the two apps -- named
``organizations`` and ``organizations_custom_data`` at the time, and renamed in
the entry above -- differs from 0.1.0.

Internal
~~~~~~~~

* Pushing a version tag now builds, checks and uploads the release from GitHub
  Actions, authenticating with PyPI trusted publishing instead of a stored API
  token. The version is dynamic, so the workflow refuses to upload when the tag
  and ``__version__`` disagree, and it can be run by hand for a tag pushed
  before the workflow existed.

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
  no changes. Resolve them with ``vinta_orgs.conf.get_organization_model()``
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
