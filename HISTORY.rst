.. :changelog:

History
-------

0.4.0 (2026-08-14)
++++++++++++++++++++

Breaking
~~~~~~~~

* **The function-based organization API is removed.** The
  ``vinta_orgs.helpers`` package, including its ``organizations`` and
  ``memberships`` modules, no longer exists. Bind the project's swapped models
  once with declarative service subclasses instead:

  .. code:: python

      from myapp.models import Organization, OrganizationMembership
      from vinta_orgs.services import MembershipService, OrganizationService

      class Organizations(OrganizationService[Organization]):
          model_class = Organization

      class Memberships(MembershipService[Organization, OrganizationMembership]):
          model_class = OrganizationMembership

      organizations = Organizations()
      memberships = Memberships()

  Replace ``create_organization`` / ``update_organization`` with
  ``organizations.create`` / ``organizations.update``;
  ``create_membership`` / ``get_active_memberships`` with
  ``memberships.create`` / ``memberships.get_active``; and the two resolver
  helpers with ``memberships.resolve_for_user`` /
  ``memberships.resolve_organization_for_user``. The default group operation is
  ``organizations.create_default_groups``. An explicitly configured
  ``ORGANIZATION_GROUP_SEEDERS`` path must change from the deleted helper to
  ``vinta_orgs.seeding.create_default_organization_groups``.

* **Organization context state is class-specialized too.** The module-level
  ``get_current_organization``, ``set_current_organization``,
  ``clear_current_organization``, ``reset_current_organization`` and
  ``organization_context`` APIs are removed, as are
  ``OrganizationMiddleware.get_current_organization()``, ``set_organization()``
  and ``clear_organization()``. Define one typed state object alongside the
  services:

  .. code:: python

      from vinta_orgs.state import OrganizationState

      class ProjectOrganizationState(OrganizationState[Organization]):
          model_class = Organization

      organization_state = ProjectOrganizationState()

  The replacements are ``organization_state.get()``, ``set()``, ``clear()``,
  ``reset()`` and ``context()``. The old ``OrganizationOrSlug`` alias and
  directly constructed ``organization_context`` class are no longer public;
  ``organization_state.context(...)`` returns the typed context manager.

* **Moving an existing row between organizations now requires an explicit
  unsafe opt-in.** Calls that previously changed ``organization`` or
  ``organization_id`` now raise ``OrganizationCannotBeUpdatedError``. Data
  migrations and other deliberately cross-tenant maintenance code pass
  ``unsafe_organization_update=True`` to ``save()``, ``update()``,
  ``bulk_update()``, ``update_or_create()`` or conflict-updating
  ``bulk_create()``. Their asynchronous forms accept the same option. This is
  the intentional security hardening described below.

* **Settings-driven model APIs no longer pretend that the package's concrete
  models are always configured.** The zero-argument model getters and other
  APIs without a concrete generic input are typed against
  ``AbstractOrganization`` / ``AbstractOrganizationMembership``. Runtime model
  resolution is unchanged. Pass the project's concrete class to
  ``get_organization_model(MyOrganization)`` /
  ``get_organization_membership_model(MyMembership)`` when a model class itself
  is needed; use the specialized services, state and ``OrganizationRequest``
  for concrete instance return types.

Security
~~~~~~~~

* Organization ownership is immutable on existing rows. ``save()``,
  ``update()``, ``bulk_update()``, ``update_or_create()`` and conflict-updating
  ``bulk_create()`` -- including their asynchronous forms -- refuse a change to
  ``organization`` with ``OrganizationCannotBeUpdatedError``. A deliberate data
  migration can opt in per call with ``unsafe_organization_update=True``.

Fixed
~~~~~

* Assigning ``None`` to a nullable ``OrganizationSafeForeignKey`` or
  ``OrganizationSafeOneToOneField`` clears only its target key. It no longer
  clears the row's ``organization_id`` and leaves the next save able to stamp
  the row into whichever organization happens to be bound.
* Reverse related managers and prefetches derive their scope from the source
  instance instead of requiring an ambient organization. ``bulk_update()`` can
  likewise address the primary keys of instances supplied by an unbound
  caller. Explicit-organization ``get_or_create()`` and ``update_or_create()``
  perform their lookup unscoped.
* ``validate_unique()`` and ``validate_constraints()`` run Django's database
  probes through an unscoped default manager, matching global database
  constraints and allowing model forms to validate outside a request.

Added
~~~~~

* ``unscoped_default_manager()`` is a narrow, context-local escape hatch for
  Django internals such as ``ForeignKey.formfield()`` that hard-code
  ``_default_manager`` and offer no queryset override.
* ``UNRESOLVED_ORGANIZATION`` lets a resolver for a non-slug identifier preserve
  the difference between "no identifier supplied" and "identifier supplied but
  not found" without inventing a sentinel slug.
* Organization and membership operations are centralized in generic
  ``OrganizationService`` and ``MembershipService`` classes. Applications bind
  their swapped models once through declarative ``model_class`` subclasses.
* ``MembershipService`` derives the organization model from its membership
  model's foreign key and therefore needs no organization-service constructor
  parameter. ``OrganizationState`` uses the same specialization pattern for
  typed ``get()``, ``set()`` and ``context()`` operations.
* ``OrganizationRequest`` remains generic, and organization-safe relation
  declarations now type as Django fields, allowing django-stubs to infer their
  related model.

0.3.0 (2026-08-13)
++++++++++++++++++

Breaking
~~~~~~~~

* **``STRICT_ORGANIZATION_FILTER`` now defaults to ``True``.** Querying an
  organization-scoped model with no organization selected raises
  ``OrganizationNotFoundError`` instead of returning an empty queryset. An
  unbound scoped query is nearly always a bug, and "harmless, it returns
  nothing" is only true of reads: a ``get_or_create`` with nothing selected
  looks the row up across every tenant, finds one belonging to somebody else,
  and hands it back for the caller to write to.

  Set it to ``False`` to keep the old behaviour. Code that deliberately reads
  across organizations should say so instead -- ``original_manager``,
  ``unscoped()``, ``filter_by_organization()``.

* ``IsOrganizationOwner`` and ``DjangoOrganizationModelPermissions`` answer
  ``False`` when no organization is selected rather than letting the strict
  filter raise through them. Nobody may act in an organization nobody selected,
  and a permission class that raises turns a 403 into a 500.

Fixed
~~~~~

* ``MyModel.objects.create()`` and ``bulk_create()`` no longer scope the
  queryset they are built from. Both insert without reading anything, so the
  scoping could only ever refuse a valid call: under
  ``STRICT_ORGANIZATION_FILTER`` they raised with nothing selected -- including
  ``create(organization=organization)``, which names its organization outright,
  and every ``instance.related_set.create(...)``, which Django routes through
  the same method. Which organization the row lands in is unchanged, and
  ``save()`` still refuses when none can be resolved. ``get_or_create()`` and
  ``update_or_create()`` are untouched: they look a row up first, and that
  lookup is exactly the one that must not span tenants.

Security
~~~~~~~~

* **A deactivated membership now grants nothing.**
  ``AbstractOrganizationMembership`` gains ``is_active`` (default ``True``), and
  ``OrganizationModelBackend`` filters on it *in the membership lookup*. Before
  this the field was every project's to declare, so the backend could not read
  it: deactivating an administrator left them resolving every permission their
  groups carried, through ``has_perm`` and every DRF permission class built on
  it. The permission classes shipped here, and the organization list endpoint,
  skip inactive memberships too.

* **Header and session resolution check the caller's memberships.**
  ``retrieve_by_http_header`` used to look the slug up and select it, so any
  authenticated user could select any tenant by sending its slug. It now refuses
  an organization the authenticated caller holds no active membership in, with
  ``OrganizationAccessDeniedError`` (a ``PermissionDenied``, so a 403), and
  ``retrieve_by_session`` does the same. Anonymous requests are unaffected --
  there is no membership to check and no privilege to escalate.
  ``retrieve_by_domain`` is untouched: the host is not the caller's to choose.
  Turn the check off with ``VERIFY_ORGANIZATION_MEMBERSHIP = False``.

* The new ``vinta_orgs.W001`` system check reports
  ``OrganizationMiddleware`` running before ``AuthenticationMiddleware``, which
  leaves the check above with no ``request.user`` to consult.

Added
~~~~~

* ``vinta_orgs.authorization``: ``has_organization_permission(user, permission,
  organization)`` and ``get_organization_permissions(user, organization)`` --
  "may this user do X **in organization Y**", with Y named rather than read from
  the context. ``has_perm`` cannot answer that: it resolves for the *bound*
  organization, unions in the user's global permissions and groups, and
  short-circuits for superusers. All three are privilege escalations when this
  is the question, so ``include_global`` and ``allow_superuser`` are explicit
  parameters, both off by default. ``has_perm`` itself keeps ``ModelBackend``
  semantics unchanged.

* ``membership_holds_permission(membership, permission)`` for a membership row
  the caller already holds, and ``resolve_membership_permissions(memberships)``
  for a page of them in a constant number of queries -- the backend caches per
  ``(user, organization)``, so a list endpoint was N lookups.

* ``vinta_orgs.drf.OrganizationScopedAPIViewMixin``: organization resolution for
  DRF views, in the seam between "``request.user`` is real" and
  ``check_permissions``. The middleware resolves before DRF authentication, so
  with token or JWT authentication a user-dependent organization cannot be
  resolved there at all. Binds for the request and releases in a ``finally``
  around ``dispatch``.

* ``vinta_orgs.services.MembershipService.resolve_for_user`` and its
  organization-shaped method: the full resolution table (0 / 1 / 2+ active
  memberships against a named / absent / non-member organization), with
  ``AmbiguousOrganizationError`` for a multi-organization caller who named none
  -- a 400 rather than a silent pick by row creation order -- and
  ``OrganizationAccessDeniedError`` for a non-member.
  ``retrieve_by_user_membership`` is the retriever built on it, opt-in.

* ``OrganizationMembershipQuerySet``, now the membership model's default
  queryset: ``active()``, ``active_for_user(user)`` and
  ``holding_permission('app_label.codename')`` -- the union of a membership's
  own permission grant with the permissions its groups carry, which is what a
  last-administrator guard has to count by. Reachable through the reverse
  accessors as well (``user.memberships.active()``).

* ``vinta_orgs.testing``: a reseed-at-setup pytest fixture
  (``pytest_plugins = ['vinta_orgs.testing']``), a ``TransactionTestCase`` mixin
  and ``reseed_organization_groups()``. A transactional test's flush re-emits
  ``post_migrate`` -- rebuilding content types and permissions -- but does not
  re-run data migrations, so seeded groups vanish for the rest of that worker's
  session and every membership built afterwards silently holds nothing.
  ``ORGANIZATION_GROUP_SEEDERS`` lists a project's own seeders.

Migrations
~~~~~~~~~~

* ``vinta_orgs/0002_organizationmembership_is_active`` adds the column. On a
  project that swapped ``ORGANIZATION_MEMBERSHIP_MODEL`` it is a no-op and the
  column arrives through that app's own migration instead -- generated from the
  abstract base, and an ``AlterField`` rather than an ``AddField`` if the
  project already had an ``is_active`` of its own.

Documentation
~~~~~~~~~~~~~

* How to empty the abstract base's ``Meta.unique_together`` and keep your own
  named constraint.

* What ``OrganizationSafeForeignKey``'s two-field shape means for fixtures --
  ``baker.make`` refuses a model with one unless the relation is passed under
  its declared name.

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
