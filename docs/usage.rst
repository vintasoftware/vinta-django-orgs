=====
Usage
=====

Instalation on Django
---------------------

To use Django Shared Schema Organizations in a project, add it to your `INSTALLED_APPS`:

.. code-block:: python

    INSTALLED_APPS = (
        ...
        'organizations.apps.OrganizationsConfig',
        ...
    )

Add Django Shared Schema Organizations's URL patterns:

.. code-block:: python

    from organizations import urls as organizations_urls


    urlpatterns = [
        ...
        url(r'^', include(organizations_urls)),
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

    from organizations.mixins import SingleOrganizationModelMixin, MultipleOrganizationsModel

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

    from organizations.models import AbstractOrganization, AbstractOrganizationMembership

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
        is_active = models.BooleanField(default=True)

.. code:: python

    # settings.py
    ORGANIZATION_MODEL = 'tenancy.Organization'
    ORGANIZATION_MEMBERSHIP_MODEL = 'tenancy.OrganizationMembership'

The abstract bases carry ``name``, ``slug`` and the timestamps; the membership
base carries the organization, the user, the groups and the permissions. Your
subclass adds fields and nothing else is required of it.

Both settings are ordinary top-level Django settings rather than keys inside
``SHARED_SCHEMA_ORGANIZATIONS``, because Django's own ``Meta.swappable``
machinery reads them with a plain ``getattr(settings, ...)``. Both default to the
models in this app, so a project that does not need this never mentions them.

Reach for the configured model through the helpers, never by importing
``Organization``:

.. code:: python

    from organizations.conf import get_organization_model, get_organization_membership_model

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

    from organizations.fields import OrganizationSafeForeignKey
    from organizations.mixins import SingleOrganizationModelMixin

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

If the header ``Organization-Slug`` could be found in the request, the organization
with that slug is automatically selected.

Forcing organization selection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Outside the request/response cycle -- Celery tasks, management commands, tests
-- select the organization with ``organization_context``. It accepts a slug or
an ``Organization``, works as a context manager or as a decorator, and restores
whatever was selected before when it exits (including when the block raises):

.. code:: python

    from organizations.helpers import organization_context

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

    from organizations.helpers import clear_current_organization, set_current_organization

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

    from organizations.helpers import get_current_organization

    def my_view(request):
        current_organization = get_current_organization()
        # ...


The models that inherit from ``SingleOrganizationModelMixin`` or
``MultipleOrganizationsModelMixin`` are also organization aware. If you retrieve a
collection from database with a organization context in your request, your
collection will already be filtered by that organization.



Configuration options
---------------------

To configure how Django Shared Schema Organizations works you can set a bunch of options in the SHARED_SCHEMA_ORGANIZATIONS dictionary in django settings

SERIALIZERS
~~~~~~~~~~~
It's a dict where you can replace the serializers to be used in Django Shared Schema Organizations REST API endpoints.
default value:

.. code:: python

    {
        'ORGANIZATION_SERIALIZER': 'organizations.serializers.OrganizationSerializer',
        'ORGANIZATION_SITE_SERIALIZER': 'organizations.serializers.OrganizationSiteSerializer',
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

default value: derived, e.g. ``['organizations.add_organization', ...]``


DEFAULT_SITE_DOMAIN
~~~~~~~~~~~~~~~~~~~

In here you define your default site domain.

default value: ``'localhost'``


ORGANIZATION_HTTP_HEADER
~~~~~~~~~~~~~~~~~~~~~~~~

In here you can defined which http header we should use to extract the organization slug

default value: ``'Organization-Slug'``


STRICT_ORGANIZATION_FILTER
~~~~~~~~~~~~~~~~~~~~~~~~~~

When no organization is selected, querying an organization-aware model returns
an empty queryset. Set this to ``True`` to raise ``OrganizationNotFoundError``
instead: an empty result is hard to tell from "no data yet", and in a task or a
management command a missing selection is the likelier explanation.

Explicitly scoped reads (``filter_by_organization``, ``unscoped``,
``original_manager``) are unaffected. So is ``MyModel.objects.none()``: it asks
for no rows and so cannot return another organization's, which is what makes it
usable to express a denied read in a view and safe for schema generators to call
outside any request.

default value: ``False``


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
