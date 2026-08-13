=====
Usage
=====

Instalation on Django
---------------------

To use Django Shared Schema Organizations in a project, add it to your `INSTALLED_APPS`:

.. code-block:: python

    INSTALLED_APPS = (
        ...
        'vinta_orgs.apps.OrganizationsConfig',
        ...
    )

Add Django Shared Schema Organizations's URL patterns:

.. code-block:: python

    from vinta_orgs import urls as vinta_orgs_urls


    urlpatterns = [
        ...
        url(r'^', include(vinta_orgs_urls)),
        ...
    ]


Create new organizations
------------------------

Run ``python manage.py createorganization`` to create you first organization


Turning existing models into a Organization Model
-------------------------------------------------

The models become organization aware through inheritance. You just have to
make your model inherit from ``SingleOrganizationModelMixin`` or
``MultipleOrganizationsModelMixin`` and you’re set.

.. code:: python

    from vinta_orgs.mixins import SingleOrganizationModelMixin, MultipleOrganizationsModel

    class MyModelA(SingleOrganizationModelMixin)
        field1 = models.CharField(max_length=100)
        field2 = models.IntegerField()

    # ...

    # 'default' organization selected
    instance = MyModelA(field1='test default organization', field2=0)
    instance.save()

    # ...

    # 'other' organization selected
    instance = MyModelA(field1='test other organization', field2=1)
    instance.save()

    print(MyModel.objects.filter(field1__icontains="test"))
    # prints only the instance with 'test other organization' in field1


Using your own organization model
---------------------------------

``Organization`` and ``OrganizationMembership`` are swappable, the way
``auth.User`` is. When you need a field on either -- a parent organization, a
reseller flag, a deactivated-member marker -- declare your own model on the
matching abstract base instead of hanging a one-to-one companion off the one
shipped here:

.. code:: python

    # tenancy/models.py
    from django.db import models

    from vinta_orgs.models import AbstractOrganization, AbstractOrganizationMembership

    class Organization(AbstractOrganization):
        parent = models.ForeignKey('self', null=True, blank=True,
                                   related_name='children', on_delete=models.PROTECT)
        can_invite_organizations = models.BooleanField(default=False)

        class Meta(AbstractOrganization.Meta):
            constraints = [
                models.UniqueConstraint(fields=['parent', 'name'],
                                        name='uniq_organization_name_per_parent'),
            ]

    class OrganizationMembership(AbstractOrganizationMembership):
        notes = models.TextField(blank=True)

.. code:: python

    # settings.py
    ORGANIZATION_MODEL = 'tenancy.Organization'
    ORGANIZATION_MEMBERSHIP_MODEL = 'tenancy.OrganizationMembership'

The abstract bases carry ``name``, ``slug`` and the timestamps; the membership
base carries the organization, the user, the groups, the permissions and
``is_active``. Your subclass adds fields and nothing else is required of it.

Replacing the membership's uniqueness constraint
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``AbstractOrganizationMembership.Meta`` declares
``unique_together = [('user', 'organization')]``, and Django names that
constraint after your app and model. If you need the name under your own control
-- raw SQL that references it, a foreign key bound to it by name, a constraint
your operations team already documented -- empty the inherited one and declare
your own:

.. code:: python

    class OrganizationMembership(AbstractOrganizationMembership):
        class Meta(AbstractOrganizationMembership.Meta):
            unique_together = []
            constraints = [
                models.UniqueConstraint(fields=['user', 'organization'],
                                        name='uniq_membership_user_per_organization'),
            ]

The guarantee is identical; only the name moves. Emptying ``unique_together``
without putting a ``UniqueConstraint`` back leaves the model with nothing
stopping two memberships for the same pair.

Both settings are ordinary top-level Django settings rather than keys inside
``SHARED_SCHEMA_ORGANIZATIONS``, because Django's own ``Meta.swappable``
machinery reads them with a plain ``getattr(settings, ...)``. Both default to the
models in this app, so a project that does not need this never mentions them.

Reach for the configured model through the helpers, never by importing
``Organization``:

.. code:: python

    from vinta_orgs.conf import get_organization_model, get_organization_membership_model

    Organization = get_organization_model()
    OrganizationMembership = get_organization_membership_model()

For a foreign key of your own, point at the setting so it follows the swap:

.. code:: python

    from django.conf import settings

    class Invoice(SingleOrganizationModelMixin):
        billed_to = models.ForeignKey(settings.ORGANIZATION_MODEL, on_delete=models.PROTECT)

**Decide before your first migration.** This has the same sharp edge as
``AUTH_USER_MODEL``: swapping after tables exist means migrating data between
them by hand, because every organization-scoped table in the project has a
foreign key pointing at the old one. Swapping on a greenfield project costs
nothing.

A project that swaps a model and wants its own admin for it should
``admin.site.unregister(...)`` first -- this app registers whichever models are
configured.


Querying other organizations
----------------------------

``MyModel.objects`` is scoped to the selected organization. When you need to
step outside that scope, say so explicitly. The same methods exist on the
manager and on the queryset, so they chain after any other lookup:

.. code:: python

    # Another organization, whichever one is currently selected
    MyModel.objects.filter_by_organization(other_organization)
    MyModel.objects.exclude_by_organization(other_organization)

    # Every organization -- reports, migrations, maintenance commands
    MyModel.objects.unscoped()

    # Chaining, on any queryset
    MyModel.original_manager.filter(field2__gt=0).filter_by_organization(other_organization)
    MyModel.original_manager.filter(field2__gt=0).for_current_organization()

``with_organization()`` (``with_organizations()`` on
``MultipleOrganizationsModelMixin``) fetches the related organizations in the
same query, which is worth doing whenever you read ``instance.organization``
while iterating:

.. code:: python

    for instance in MyModel.objects.with_organization():
        print(instance.organization.name)  # no query per row


Memberships are not scoped
--------------------------

``OrganizationMembership`` is the one exception to all of the above: its default
manager reads every organization.

A membership is metadata *about* the tenancy rather than data inside it. It is
the table you read to work out which organization to select, so scoping it to
the organization already selected is circular -- and the queries that need it are
the ones that run before anything has been selected:

.. code:: python

    # The organization switcher: which organizations may this user select?
    user.memberships.select_related('organization')

    # Provisioning, immediately after signup
    create_membership(organization, user)

    # Is this invitation's user already a member?
    OrganizationMembership.objects.filter(user=user, organization=organization).exists()

This is inherited by the reverse accessors, which is most of the point: Django
builds ``user.memberships`` and ``organization.memberships`` from the model's
default manager, so a scoped one carried the scoping into exactly the lookups
that cannot work under it.

When you do want one organization, say so -- the scoping methods are all still
there, on the manager and on the reverse accessors alike:

.. code:: python

    user.memberships.for_current_organization()
    OrganizationMembership.objects.filter_by_organization(organization)

    # Or the implicitly scoped manager, inherited from the mixin
    OrganizationMembership.organization_objects.all()

**This matters most in permission checks.** Anything that asks "is this user an
owner?" has to name the organization it means, or it will answer "an owner of
*something*". The permission classes shipped here narrow with
``for_current_organization()`` for exactly this reason; check your own.


Deactivating a member
---------------------

``OrganizationMembership.is_active`` is the membership's soft delete. Unset it
rather than deleting the row, and the audit trail, the invitations and anything
else pointing at the membership survive:

.. code:: python

    membership.is_active = False
    membership.save()

An inactive membership grants nothing and selects nothing. Specifically:

* the permission backend resolves no permissions from it, so ``has_perm`` and
  every DRF permission class built on it refuse -- a deactivated administrator
  is exactly as powerful as a non-member;
* the retrievers will not select its organization for that user;
* ``resolve_membership_for_user`` treats it as absent, so it does not make a
  single-organization caller look ambiguous;
* the permission classes and the organization list endpoint shipped here skip
  it.

The gate is in the lookup, not in a "clear the groups on deactivation" side
effect. Deactivation happens on more than one code path in most projects, a
side effect has to be remembered on every one of them, and reactivation then
needs a restore step that knows what to put back. A filter cannot be forgotten.

The membership-shaped lookups say the same thing in a queryset:

.. code:: python

    user.memberships.active()
    OrganizationMembership.objects.active_for_user(user)          # oldest first, organization fetched
    OrganizationMembership.objects.holding_permission('tenancy.manage_members')

``holding_permission`` is the union of a membership's own ``permissions`` grant
with the permissions its ``groups`` carry, and it is what a last-administrator
guard has to count by: "how many members can still manage members" is that
queryset's ``count()``, narrowed to the organization. It reads the same two
sources the permission backend reads, and neither reads the user's *global*
permissions, so the guard and the gate cannot disagree.


May this user do X in organization Y?
-------------------------------------

``user.has_perm('tenancy.manage_members')`` does not answer that question. It
answers a different one, and the two agree often enough that the difference is
easy to miss:

* **The organization is ambient.** ``has_perm`` resolves organization
  permissions for whichever organization is *bound*, so it cannot be asked about
  another one -- an ancestor organization in a reseller hierarchy, say -- and it
  answers "no permissions at all" from a view that binds nothing.
* **The global half.** ``has_perm`` unions in ``user.user_permissions`` and the
  user's own ``auth.Group`` rows. Neither is scoped to an organization, so one
  grant made once in the Django admin is a grant in *every* organization.
* **The superuser short-circuit.** A superuser passes before any backend runs.

Name the organization instead:

.. code:: python

    from vinta_orgs.authorization import has_organization_permission

    class IsOrganizationAdmin(BasePermission):
        def has_permission(self, request, view):
            return has_organization_permission(
                request.user, 'tenancy.manage_members', request.organization
            )

It answers from an **active membership in the organization named**, and from
nothing else. The organization may be an instance or a primary key; when it is
the one already bound, the check costs no extra query. Both widening sources are
available, off by default, and worth being explicit about when you want them:

.. code:: python

    has_organization_permission(user, perm, organization, include_global=True)
    has_organization_permission(user, perm, organization, allow_superuser=True)

``has_perm`` itself is unchanged and keeps ``ModelBackend`` semantics --
superuser passes, global grants union in -- because that is what the Django
admin and ``DjangoModelPermissions`` expect of it. Use it where you want that
answer; use this where you want the other one.

Two more shapes of the same question:

.. code:: python

    from vinta_orgs.authorization import membership_holds_permission, resolve_membership_permissions

    # A membership row you already hold
    membership_holds_permission(membership, 'tenancy.manage_members')

    # A whole page of memberships, in a constant number of queries
    resolve_membership_permissions(page)   # {membership pk: sorted permission labels}

``resolve_membership_permissions`` exists because the backend caches per
``(user, organization)``: a page of N memberships is N lookups through it, which
is what anyone exposing memberships over an API hits on their first list
endpoint. It walks prefetched relations instead, and reports exactly what the
backend would resolve -- an inactive membership, or an inactive user, publishes
the empty list.


Relations that check the organization
-------------------------------------

A plain ``ForeignKey`` between two organization-aware models joins on the key
alone, so nothing in the join says the two rows belong to the same
organization. The managers scope the outermost query, but a relation traversal
-- ``select_related('article')``, ``comment.article``,
``filter(article__title=…)`` -- reaches whatever row the key points at.

``OrganizationSafeForeignKey`` and ``OrganizationSafeOneToOneField`` put the
organization into the JOIN's ON clause:

.. code:: python

    from vinta_orgs.fields import OrganizationSafeForeignKey
    from vinta_orgs.mixins import SingleOrganizationModelMixin

    class Comment(SingleOrganizationModelMixin):
        article = OrganizationSafeForeignKey(Article, on_delete=models.CASCADE,
                                             related_name='comments')
        text = models.TextField()

.. code:: sql

    -- Comment.objects.select_related('article')
    INNER JOIN articles_article
       ON (articles_comment.article_fk_id = articles_article.id
      AND articles_comment.organization_id = articles_article.organization_id)

A row pointing at another organization's article simply does not join: it reads
as missing (``Article.DoesNotExist``, or absent from the results) rather than as
someone else's data.

Each declaration contributes two fields. ``article_fk`` is the real
``ForeignKey`` -- it owns the column, the database constraint and the cascade.
``article`` is the organization-checked relation, and it is the one to
traverse. Reads, filters and ``select_related`` therefore get the check by
default, while writes keep looking like an ordinary foreign key:

.. code:: python

    Comment.objects.create(article=article, text='…')   # also copies the organization over
    Comment(article_id=article.id, text='…')
    comment.article = article

    comment.save(update_fields=['article'])
    Comment.objects.bulk_update(comments, ['article'])
    Comment.objects.filter(...).update(article=other_article)

Passing the instance is preferred over the id: Django's descriptor copies the
target's organization onto the new row, so the two cannot drift apart.

The same reasoning decides what each write persists. ``save(update_fields=…)``
and ``bulk_update`` have an instance in hand, whose organization the descriptor
has already kept in step, so naming the relation writes *both* of its columns --
reassigning to an article in another organization moves the comment along with
it, exactly as a full ``save()`` would.

A queryset ``update()`` has no instance and matches many rows at once, so it
writes the key only. Writing the organization there would silently move every
matched row into the target's organization, which is a worse failure than the
one it would prevent. Point ``update()`` at a target in the same organization;
if you do not, the rows read as missing through the relation rather than as
another organization's data.

Both models must be organization-aware, since the join reads ``organization_id``
on each side. Note that the check is at the ORM level -- the database is not
stopping a mismatched row from being written by raw SQL, it just will not be
readable through the relation.

Two fields, and what that means for fixtures
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The two-field shape is invisible to application code, which is the point, but it
is *not* invisible to anything that walks ``Model._meta.get_fields()`` and fills
each one in -- which is what a fixture factory does.

``Comment`` reports both ``article`` (a ``ForeignObject``, no column of its own)
and ``article_fk`` (the real ``ForeignKey``). ``model_bakery`` does not know what
to do with the first one, so it refuses:

.. code:: python

    baker.make(Comment)
    # TypeError: field article type <class 'django.db.models.fields.related.ForeignObject'>
    #            is not supported by baker.

    baker.make(Comment, article_fk=article)   # same TypeError: `article` is still unfilled

**Always pass the relation under its declared name.** That is the one spelling
baker accepts, and it is also the one that does the right thing -- the
descriptor copies the target's organization onto the new row, so the two cannot
drift apart:

.. code:: python

    baker.make(Comment, article=article)               # article_fk and organization both set
    baker.prepare(Comment, article=article)
    baker.make(Comment, article=article, _quantity=2)

If you are converting an existing suite, the sweep is mechanical -- every
``baker.make`` of a model with a safe relation has to name that relation -- but
it is not optional, because the failure is a hard ``TypeError`` at every such
call site rather than something you can leave for later.

``get_or_create``, ``update_or_create`` and ``filter`` take either name, and
mean the same thing by both:

.. code:: python

    Comment.objects.get_or_create(article=article, defaults={'text': '…'})
    Comment.objects.filter(article=article)


CACHE_ORGANIZATION_RETRIEVAL
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``retrieve_by_domain`` is the first retriever a request tries, and it costs one
query mapping the site to its organization -- on every request that reads
organization-scoped data. Set this to ``True`` to cache that mapping:

.. code:: python

    SHARED_SCHEMA_ORGANIZATIONS = {
        'CACHE_ORGANIZATION_RETRIEVAL': True,
        'ORGANIZATION_CACHE_ALIAS': 'default',
        'ORGANIZATION_CACHE_TIMEOUT': 300,
    }

**Off by default, deliberately.** A stale entry here does not make a page slow,
it serves one organization's data to another. Two things bound that risk:
writing an ``Organization`` or an ``OrganizationSite`` drops the affected
entries, and entries expire on their own, so a write that bypasses Django --
raw SQL, a restore, another service sharing the database -- is corrected within
``ORGANIZATION_CACHE_TIMEOUT`` rather than never. If writes to those two tables
only ever happen through Django, the invalidation is exact and the timeout is
just a safety net.

The organization is cached as its column values rather than as a pickled model,
so a deploy that adds or removes a field reads as a miss instead of
reconstructing an instance that no longer matches the table.

default value: ``False``


Filtering across a safe relation
--------------------------------

``filter(article__status='published')`` joins, and the organization-safe join
is one PostgreSQL misestimates -- it costs the key match and the organization
match as though they were independent, so under a ``LIMIT`` it builds the whole
join and sorts it to return one page. ``filter_related_without_join()`` tests
each row instead:

.. code:: python

    Comment.objects.filter_related_without_join(article__status='published')[:50]

**It is a trade, not a free win.** The page is filled by walking the
organization's rows in primary key order and checking each one, so it is fast
when matches are common and slow when they are rare. Measured on 25
organizations of 3,000 articles each, a page of 50:

=========================  ======  ==============================
Filter matches             join    filter_related_without_join
=========================  ======  ==============================
1 in 3 articles            1.854   0.382
~1 in 100                  0.508   0.306
~1 in 1000                 0.507   6.345
nothing                    0.668   6.579
=========================  ======  ==============================

With nothing to find it walks everything the organization owns. PostgreSQL's
join is the safer default precisely because it bounds that case -- reach for
this when you know the filter is not selective, and measure if you are unsure.

Rows are matched exactly as the relation would match them, organization
included: a comment pointing at another organization's article does not match.
Only relations declared with ``OrganizationSafeForeignKey`` or
``OrganizationSafeOneToOneField`` are accepted; an ordinary foreign key joins on
the key alone, is estimated correctly, and has nothing to gain.


Selecting organization on requests
----------------------------------

Organization site
~~~~~~~~~~~~~~~~~

If you access the site from a domain registered to a organization, that organization
is automatically selected.

Organization-Slug HTTP header
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If the header ``Organization-Slug`` is present, the organization with that slug
is selected -- **provided the caller is an active member of it**. An
authenticated caller naming an organization they do not belong to is refused
with ``OrganizationAccessDeniedError`` (a ``PermissionDenied``, so a 403), and
so is one whose membership has been deactivated. A slug matching no
organization at all still raises ``OrganizationNotFoundError``, as it always
has -- so this retriever does distinguish "not yours" from "no such thing". Use
``resolve_membership_for_user`` (below) where that distinction must not be
observable.

The header is set by whoever is making the request. Without that check, any
authenticated user selects any tenant by typing its slug, and every scoped
manager in the process then serves that tenant's rows. ``retrieve_by_domain``
needs nothing of the sort, because the host is not the caller's to choose.

Two cases are let through deliberately: an anonymous request (no membership to
check, no privilege to escalate -- the caller gets what that organization
exposes publicly, exactly as they would by visiting its domain), and a request
with no ``request.user`` at all, which is what ``AuthenticationMiddleware`` not
having run yet looks like. **Put ``OrganizationMiddleware`` after
``AuthenticationMiddleware``**; the ``vinta_orgs.W001`` system check reports it
if you have not. ``retrieve_by_session`` is checked the same way.

Set ``VERIFY_ORGANIZATION_MEMBERSHIP`` to ``False`` to skip the check.

The caller's own membership
~~~~~~~~~~~~~~~~~~~~~~~~~~~

``retrieve_by_user_membership`` selects the authenticated caller's organization
when they have exactly one. It is not in ``ORGANIZATION_RETRIEVERS`` by default;
add it *last*, after the retrievers that read something the caller said:

.. code:: python

    SHARED_SCHEMA_ORGANIZATIONS = {
        'ORGANIZATION_RETRIEVERS': [
            'vinta_orgs.organization_retrievers.retrieve_by_domain',
            'vinta_orgs.organization_retrievers.retrieve_by_http_header',
            'vinta_orgs.organization_retrievers.retrieve_by_user_membership',
        ],
    }

A caller with several memberships and nothing naming one raises
``AmbiguousOrganizationError`` (a ``BadRequest``, so a 400) rather than
resolving to whichever membership is oldest. Picking one means the request reads
and writes an organization the caller never named, chosen by row creation order:
a user who administers an old organization A and is a plain member of B would
pass an administrator gate for a request that then serves B.

The whole table lives in
``vinta_orgs.helpers.memberships.resolve_membership_for_user``, which you can
call directly:

==================  ==============================  =====================================
Active memberships  slug named by the caller         Result
==================  ==============================  =====================================
any                 -- anonymous caller             ``None``
any                 names one of them               that membership
any                 names anything else             ``OrganizationAccessDeniedError``
0                   absent                          ``None``
1                   absent                          that membership
2+                  absent                          ``AmbiguousOrganizationError``
==================  ==============================  =====================================

Pass ``strict=False`` to turn both refusals into ``None``. That is for the
endpoints which must work *before* an organization is selected -- the
organization switcher, onboarding, accepting an invitation -- not a default to
reach for.

Django REST Framework
~~~~~~~~~~~~~~~~~~~~~

The middleware resolves at Django-middleware time, which is **before DRF
authentication**. With session authentication that is fine. With token, JWT or
any other DRF authentication class it is not: ``request.user`` is anonymous at
that point, so a header cannot be checked against the caller and there is no
membership to fall back on.

``OrganizationScopedAPIViewMixin`` moves the resolution into the one seam
between "``request.user`` is real" and "``check_permissions`` runs":

.. code:: python

    from rest_framework import viewsets
    from vinta_orgs.drf import OrganizationScopedAPIViewMixin

    class BaseViewSet(OrganizationScopedAPIViewMixin, viewsets.ModelViewSet):
        pass

Every request then carries ``request.organization`` and
``request.organization_membership``, and the organization is bound to the
context every scoped manager reads -- so ``MyModel.objects`` inside the view
answers for it. The binding is released in a ``finally`` around the whole of
``dispatch``, which is the only placement with no exit path around it:
``finalize_response`` does not run when DRF re-raises an exception it has no
response for, and a binding that outlived the request would be read by the next
request the worker serves.

Resolving *before* ``check_permissions`` is the point. Resolving after it means
permission classes answer for one organization while ``get_queryset`` serves
another.

Views that must work before an organization is selected opt out, either for the
whole class or for one action:

.. code:: python

    class OrganizationViewSet(BaseViewSet):
        organization_optional_actions = ('mine',)

    class OnboardingView(OrganizationScopedAPIViewMixin, APIView):
        organization_resolution_optional = True

The 400 and the 403 are then suppressed and the organization resolves to
``None`` instead. Write those views against an unbound context; under
``STRICT_ORGANIZATION_FILTER`` a scoped read from one raises rather than quietly
returning nothing.

The middleware can stay in ``MIDDLEWARE`` alongside the mixin -- it resolves the
non-DRF surface, and the mixin's binding replaces its own for the duration of
the view and restores it on the way out.

Forcing organization selection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Outside the request/response cycle -- Celery tasks, management commands, tests
-- select the organization with ``organization_context``. It accepts a slug or
an ``Organization``, works as a context manager or as a decorator, and restores
whatever was selected before when it exits (including when the block raises):

.. code:: python

    from vinta_orgs.helpers import organization_context

    from .models import MyModel

    def my_function():
        with organization_context('default'):
            return list(MyModel.objects.all())  # only organization__slug='default'


    @organization_context('default')
    def my_task():
        return MyModel.objects.count()

``set_current_organization`` selects an organization without a scope, and
``clear_current_organization`` unselects it. Prefer ``organization_context``:
a bare ``set_current_organization`` stays in effect for the rest of the thread
(or async task), which is rarely what a helper function wants.

.. code:: python

    from vinta_orgs.helpers import clear_current_organization, set_current_organization

    set_current_organization('default')
    # ...
    clear_current_organization()

The selection is stored in a ``contextvars.ContextVar``, so it is isolated per
thread and per async task, and the middleware restores the previous value when
the response is returned.

Accessing current organization
------------------------------

From Request
~~~~~~~~~~~~

You can access the current organization from the request.

.. code:: python

    def my_view(request):
        current_organization = request.organization
        # ...


From ``get_current_organization`` helper
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: python

    from vinta_orgs.helpers import get_current_organization

    def my_view(request):
        current_organization = get_current_organization()
        # ...


The models that inherit from ``SingleOrganizationModelMixin`` or
``MultipleOrganizationsModelMixin`` are also organization aware. If you retrieve a
collection from database with a organization context in your request, your
collection will already be filtered by that organization.



Seeded groups and transactional tests
-------------------------------------

Roles are best expressed as seeded ``auth.Group`` rows -- a data migration
creates them, memberships go in them, and every check reads a permission rather
than a role name. ``create_default_organization_groups()`` seeds
``organization_owner`` that way.

**This breaks the moment a test flushes the database, and it breaks silently.**

A test that runs in a real transaction -- ``TransactionTestCase``, or
``@pytest.mark.django_db(transaction=True)`` -- flushes every table when it
finishes. ``flush`` re-emits ``post_migrate``, so content types and permissions
are rebuilt by Django's own receivers, but nothing rebuilds rows a *data
migration* wrote. The groups, and every ``auth_group_permissions`` row hanging
off them, are gone for the rest of that worker's session.

What that looks like is not "a missing group". Both test runners group
transactional tests together and run them after the rest, so only the first one
sees a seeded database; from then on every membership a test builds silently
holds no permission at all, and the failures land in whichever unrelated module
asserts on a permission next. It reads as flakiness, or as parallel load.

The repair has to be at **setup**: the flush happens in the runner's own
finalizer, after any teardown hook a test could install, so there is no hook late
enough.

With pytest, add the plugin to your root ``conftest.py``:

.. code:: python

    pytest_plugins = ['vinta_orgs.testing']

Its autouse fixture reseeds before every test that has a database, and leaves
tests without one alone.

With Django's runner, mix into the test cases that flush:

.. code:: python

    from vinta_orgs.testing import SeededOrganizationGroupsMixin

    class MyFlowTests(SeededOrganizationGroupsMixin, TransactionTestCase):
        ...

Or call ``reseed_organization_groups()`` yourself. It is idempotent and additive
-- it does not revoke a permission a test attached on purpose -- and when
nothing was destroyed it costs one ``get_or_create`` that finds its row and
stops.

If you seed more groups than the one shipped here, list *the same callables your
data migration calls* rather than copying their contents:

.. code:: python

    SHARED_SCHEMA_ORGANIZATIONS = {
        'ORGANIZATION_GROUP_SEEDERS': [
            'vinta_orgs.helpers.organizations.create_default_organization_groups',
            'myproject.organizations.groups.create_role_groups',
        ],
    }

This has to reproduce *head* state. A data migration is entitled to stop
describing what the code now expects; the seeder is not.

Seeders run with no organization bound, since they run before the test that
would bind one. Groups are global rows, so that only constrains a project which
has hung organization-scoped state off ``auth.Group``.


Configuration options
---------------------

To configure how Django Shared Schema Organizations works you can set a bunch of options in the SHARED_SCHEMA_ORGANIZATIONS dictionary in django settings

SERIALIZERS
~~~~~~~~~~~
It's a dict where you can replace the serializers to be used in Django Shared Schema Organizations REST API endpoints.
default value:

.. code:: python

    {
        'ORGANIZATION_SERIALIZER': 'vinta_orgs.serializers.OrganizationSerializer',
        'ORGANIZATION_SITE_SERIALIZER': 'vinta_orgs.serializers.OrganizationSiteSerializer',
        'ORGANIZATION_MEMBERSHIP_SERIALIZER': None,
    }

DEFAULT_ORGANIZATION_SLUG
~~~~~~~~~~~~~~~~~~~~~~~~~

In here you can define you default organization (organization to be use in case the middleware can't retrieve the organization from the request)

Set it to ``None`` when there is no catch-all organization and every row must
belong to one the caller selected. Saving a scoped model with nothing selected
then raises ``OrganizationNotFoundError`` without looking a default up first.

default value: ``'default'``


DEFAULT_ORGANIZATION_OWNER_PERMISSIONS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The permissions ``create_default_organization_groups()`` puts in the
``organization_owner`` group.

The default is derived from the configured models rather than hardcoded, so it
follows ``ORGANIZATION_MODEL`` and ``ORGANIZATION_MEMBERSHIP_MODEL``: add,
change and delete on the organization, the membership and ``OrganizationSite``.
A permission that does not exist is skipped silently when the group is built, so
a hardcoded list naming the wrong app label produced an empty owner group and a
403 on every organization endpoint.

default value: derived, e.g. ``['vinta_orgs.add_organization', ...]``


DEFAULT_SITE_DOMAIN
~~~~~~~~~~~~~~~~~~~

In here you define your default site domain.

default value: ``'localhost'``


ORGANIZATION_HTTP_HEADER
~~~~~~~~~~~~~~~~~~~~~~~~

In here you can defined which http header we should use to extract the organization slug

default value: ``'Organization-Slug'``


VERIFY_ORGANIZATION_MEMBERSHIP
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When ``True``, the retrievers that read a *caller-supplied* organization --
``retrieve_by_http_header`` and ``retrieve_by_session``, never
``retrieve_by_domain`` -- refuse one the authenticated caller holds no active
membership in, with ``OrganizationAccessDeniedError`` (a 403).

Turn it off only when the header is a routing hint in front of a surface that
authorizes every read on its own. With it off, an authenticated caller selects
any tenant by sending its slug.

Requires ``OrganizationMiddleware`` to run *after* ``AuthenticationMiddleware``,
since the check reads ``request.user``. The ``vinta_orgs.W001`` system check
reports the other order.

default value: ``True``


STRICT_ORGANIZATION_FILTER
~~~~~~~~~~~~~~~~~~~~~~~~~~

Querying an organization-aware model with no organization selected raises
``OrganizationNotFoundError``. Set this to ``False`` to return an empty queryset
instead.

An unbound scoped query is nearly always a bug, and the "harmless, it just
returns nothing" reading is only true of reads:

.. code:: python

    # With nothing selected, and STRICT_ORGANIZATION_FILTER off:
    MyModel.objects.get_or_create(external_id='abc123', defaults={...})

That looks the row up across *every* tenant. It finds one belonging to somebody
else, hands it back as though it were this caller's, and the code that follows
writes to it. Nothing raises, nothing logs, and the cross-tenant write is
discovered later by whoever notices the data. On, the same line raises at the
point that forgot to select an organization.

Three things do **not** raise, because none of them reads a row that could
belong to another organization:

* explicitly scoped queries -- ``filter_by_organization()``, ``unscoped()``,
  ``original_manager``;
* ``MyModel.objects.none()``, which asks for no rows at all. That is what makes
  it usable to express a denied read in a view, and safe for schema generators
  to call outside any request;
* ``MyModel.objects.create()`` and ``bulk_create()``, which insert without
  looking anything up. ``create()`` still resolves the organization from the
  explicit ``organization=``, then the selected one, then
  ``DEFAULT_ORGANIZATION_SLUG``, and still raises when none of the three
  produced one -- the refusal comes from ``save()`` rather than from the query.
  ``instance.related_set.create(...)`` goes through the same method.

``get_or_create()`` and ``update_or_create()`` are deliberately not in that
list: they look a row up first, and that lookup is the dangerous one above.

Views that deliberately run unbound -- the organization switcher, onboarding --
read through ``original_manager`` or scope explicitly, which is the point: an
unbound scoped read becomes a decision rather than an accident.

default value: ``True``


ORGANIZATION_GROUP_SEEDERS
~~~~~~~~~~~~~~~~~~~~~~~~~~

Import paths of the callables that build your seeded organization groups. Read
only by ``vinta_orgs.testing`` -- see `Seeded groups and transactional tests`_.

default value: ``[]``, meaning
``['vinta_orgs.helpers.organizations.create_default_organization_groups']``


AUTO_DEFER_SAFE_JOINS
~~~~~~~~~~~~~~~~~~~~~

A paged query that ``select_related`` an organization-safe relation collects the
page in a subquery before joining, instead of joining and then cutting the
result down to a page::

    Comment.objects.select_related('article').order_by('id')[:50]

    # emitted as, in one query:
    #   SELECT … FROM comment JOIN article ON (…)
    #   WHERE comment.id IN (SELECT id FROM comment WHERE … ORDER BY id LIMIT 50)

The join these relations produce matches on the organization as well as on the
key. PostgreSQL costs those two conditions as though they were independent --
they are not, the organization match is implied by the key match -- so it
underestimates the join by roughly the number of organizations, and past a few
dozen it abandons the index walk that could have stopped at the end of the page
for a hash join it has to sort. The misestimate grows with the number of
organizations, so no index fixes it. Collecting the page first hands the planner
a set of rows instead of an estimate.

Measured on 100 organizations of 3,000 articles each: 3.690 ms joined directly
against 1.568 ms, both a single query. Only paged reads over a safe relation are
affected -- plain foreign keys, unpaged reads and aggregates are untouched, and
aggregates in particular are much *faster* through a safe relation than a plain
one.

On a backend that cannot put a sliced subquery inside ``IN`` -- MySQL, which
sets ``allow_sliced_subqueries_with_in = False`` -- the related rows are fetched
in a second query instead, which costs a round trip but is equally free of the
estimate.

Set this to ``False`` to join directly and page afterwards.

default value: ``True``
