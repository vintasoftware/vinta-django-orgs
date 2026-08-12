"""One API over three multi-tenancy strategies.

The scenarios in :mod:`benchmarks.scenarios` are written once, against the
methods defined here. Each adapter is responsible for exactly the differences
between the approaches -- how a tenant is bound, and how a queryset gets scoped
-- so a scenario cannot accidentally be generous to one of them.

Adapters are imported lazily by :func:`get_adapter` because importing an
adapter imports its models, and each approach needs its own settings module
loaded first.
"""

import datetime
from contextlib import contextmanager

from benchmarks.config import tenant_slug

#: Every article gets a status from this cycle, so ``published`` selects a
#: predictable third of the rows in every approach.
STATUSES = ['published', 'draft', 'archived']

BASE_DATETIME = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)


class BaseAdapter:
    """Interface the scenarios rely on."""

    key = ''
    label = ''
    #: Set by adapters whose join is organization-checked; the plain-foreign-key
    #: comparison only means something where both relations exist.
    has_safe_relations = False

    def __init__(self):
        self.tenant_ids = []
        self.current = None

    # -- setup ---------------------------------------------------------------

    def migrate(self):
        """Create the tables. Returns nothing; timed by the caller."""
        raise NotImplementedError

    def create_tenants(self, count):
        """Create ``count`` tenants. Returns the per-tenant seconds spent."""
        raise NotImplementedError

    def seed_tenant(self, tenant, articles, comments_per_article):
        """Fill one tenant with data."""
        raise NotImplementedError

    def flush(self):
        """Drop all benchmark data (but keep the tables)."""
        raise NotImplementedError

    # -- runtime -------------------------------------------------------------

    @contextmanager
    def bind(self, tenant):
        """Make ``tenant`` the tenant subsequent queries see."""
        raise NotImplementedError

    def articles(self):
        raise NotImplementedError

    def comments(self):
        raise NotImplementedError

    def authors(self):
        raise NotImplementedError

    def new_article(self, author, title):
        """Return an unsaved article for the bound tenant."""
        raise NotImplementedError

    def new_comment(self, article, body):
        raise NotImplementedError

    def cross_tenant_counts(self):
        """Count articles per tenant, across every tenant.

        The one report a shared schema answers in a single query and a schema
        per tenant answers in one query per schema.
        """
        raise NotImplementedError

    def storage(self):
        """Return ``{'table': bytes, 'indexes': bytes}`` for the article table.

        Summed over every schema, so schema-per-tenant is charged for all of
        its copies.
        """
        raise NotImplementedError


class SharedAdapter(BaseAdapter):
    """``django-shared-schema-organizations``: one table, an organization column."""

    key = 'shared'
    label = 'shared-schema-organizations'
    has_safe_relations = True

    def __init__(self):
        super().__init__()
        from benchmarks.apps.shared_app.models import Article, Author, Comment
        from vinta_orgs.models import Organization

        self.Organization = Organization
        self.Author = Author
        self.Article = Article
        self.Comment = Comment
        self._organizations = {}

    def migrate(self):
        from django.core.management import call_command

        call_command('migrate', verbosity=0, interactive=False)

    def create_tenants(self, count):
        import time

        seconds = []

        for index in range(count):
            slug = tenant_slug(index)
            started = time.perf_counter()
            organization, _ = self.Organization.objects.get_or_create(slug=slug, defaults={'name': slug})
            seconds.append(time.perf_counter() - started)
            self._organizations[slug] = organization
            self.tenant_ids.append(slug)

        return seconds

    def _organization(self, tenant):
        if tenant not in self._organizations:
            self._organizations[tenant] = self.Organization.objects.get(slug=tenant)

        return self._organizations[tenant]

    def seed_tenant(self, tenant, articles, comments_per_article):
        organization = self._organization(tenant)

        authors = self.Author.original_manager.bulk_create(
            [self.Author(organization=organization, name='Author %d' % i) for i in range(AUTHORS_PER_TENANT)]
        )

        article_objects = self.Article.original_manager.bulk_create(
            [
                self.Article(
                    organization=organization,
                    author_fk=authors[i % len(authors)],
                    title='Article %d' % i,
                    status=STATUSES[i % len(STATUSES)],
                    views=i,
                    published_at=BASE_DATETIME + datetime.timedelta(minutes=i),
                )
                for i in range(articles)
            ]
        )

        self.Comment.original_manager.bulk_create(
            [
                self.Comment(
                    organization=organization,
                    article_fk=article,
                    plain_article=article,
                    body='Comment %d on %d' % (n, article.pk),
                )
                for article in article_objects
                for n in range(comments_per_article)
            ]
        )

    def flush(self):
        # Data only: the organizations were created (and timed) just before
        # this runs, and deleting them would cascade the tenants away too.
        self.Comment.original_manager.all().delete()
        self.Article.original_manager.all().delete()
        self.Author.original_manager.all().delete()

    @contextmanager
    def bind(self, tenant):
        from vinta_orgs.state import organization_context

        with organization_context(self._organization(tenant)):
            self.current = tenant
            yield

        self.current = None

    def articles(self):
        return self.Article.objects.all()

    def comments(self):
        return self.Comment.objects.all()

    def authors(self):
        return self.Author.objects.all()

    def new_article(self, author, title):
        return self.Article(
            author=author,
            title=title,
            status='published',
            views=0,
            published_at=BASE_DATETIME,
        )

    def new_comment(self, article, body):
        return self.Comment(article=article, plain_article=article, body=body)

    def join_relation(self):
        return 'article'

    def plain_join_relation(self):
        return 'plain_article'

    def cross_tenant_counts(self):
        from django.db.models import Count

        return list(
            self.Article.original_manager.values('organization').annotate(total=Count('id')).order_by('organization')
        )

    def storage(self):
        return _storage(['shared_app_article', 'shared_app_comment'])


class ManualAdapter(BaseAdapter):
    """A hand-written tenant column: the same shape, none of the library."""

    key = 'manual'
    label = 'manual tenant column'

    def __init__(self):
        super().__init__()
        from benchmarks.apps.manual_app.models import Article, Author, Comment, Tenant

        self.Tenant = Tenant
        self.Author = Author
        self.Article = Article
        self.Comment = Comment
        self._tenants = {}

    def migrate(self):
        from django.core.management import call_command

        call_command('migrate', verbosity=0, interactive=False)

    def create_tenants(self, count):
        import time

        seconds = []

        for index in range(count):
            slug = tenant_slug(index)
            started = time.perf_counter()
            tenant, _ = self.Tenant.objects.get_or_create(slug=slug, defaults={'name': slug})
            seconds.append(time.perf_counter() - started)
            self._tenants[slug] = tenant
            self.tenant_ids.append(slug)

        return seconds

    def _tenant(self, slug):
        """Resolve a slug to its tenant row.

        Scenarios identify tenants by slug, but the column is an integer
        foreign key -- as ``vinta_orgs.Organization`` now is, so that the
        control is not carrying a wider key than the library it controls for.
        """
        if slug not in self._tenants:
            self._tenants[slug] = self.Tenant.objects.get(slug=slug)

        return self._tenants[slug]

    def seed_tenant(self, tenant, articles, comments_per_article):
        tenant = self._tenant(tenant)

        authors = self.Author.objects.bulk_create(
            [self.Author(tenant=tenant, name='Author %d' % i) for i in range(AUTHORS_PER_TENANT)]
        )

        article_objects = self.Article.objects.bulk_create(
            [
                self.Article(
                    tenant=tenant,
                    author=authors[i % len(authors)],
                    title='Article %d' % i,
                    status=STATUSES[i % len(STATUSES)],
                    views=i,
                    published_at=BASE_DATETIME + datetime.timedelta(minutes=i),
                )
                for i in range(articles)
            ]
        )

        self.Comment.objects.bulk_create(
            [
                self.Comment(tenant=tenant, article=article, body='Comment %d on %d' % (n, article.pk))
                for article in article_objects
                for n in range(comments_per_article)
            ]
        )

    def flush(self):
        self.Comment.objects.all().delete()
        self.Article.objects.all().delete()
        self.Author.objects.all().delete()

    @contextmanager
    def bind(self, tenant):
        # Binding is free here: the tenant is a variable the call sites have to
        # remember to use. That is the trade -- no runtime cost, no safety net.
        self.current = tenant
        yield
        self.current = None

    def articles(self):
        return self.Article.objects.filter(tenant=self._tenant(self.current))

    def comments(self):
        return self.Comment.objects.filter(tenant=self._tenant(self.current))

    def authors(self):
        return self.Author.objects.filter(tenant=self._tenant(self.current))

    def new_article(self, author, title):
        return self.Article(
            tenant=self._tenant(self.current),
            author=author,
            title=title,
            status='published',
            views=0,
            published_at=BASE_DATETIME,
        )

    def new_comment(self, article, body):
        return self.Comment(tenant=self._tenant(self.current), article=article, body=body)

    def join_relation(self):
        return 'article'

    def plain_join_relation(self):
        return 'article'

    def cross_tenant_counts(self):
        from django.db.models import Count

        return list(self.Article.objects.values('tenant').annotate(total=Count('id')).order_by('tenant'))

    def storage(self):
        return _storage(['manual_app_article', 'manual_app_comment'])


class TenantsAdapter(BaseAdapter):
    """django-tenants: one PostgreSQL schema per tenant."""

    key = 'tenants'
    label = 'django-tenants (schema per tenant)'

    def __init__(self):
        super().__init__()
        from benchmarks.apps.tenant_app.models import Article, Author, Comment
        from benchmarks.apps.tenants_public.models import Client, Domain

        self.Client = Client
        self.Domain = Domain
        self.Author = Author
        self.Article = Article
        self.Comment = Comment

    def migrate(self):
        from django.core.management import call_command

        call_command('migrate_schemas', '--shared', verbosity=0, interactive=False)

    def create_tenants(self, count):
        import time

        seconds = []

        for index in range(count):
            slug = tenant_slug(index)
            started = time.perf_counter()
            client = self.Client.objects.filter(schema_name=slug.replace('-', '_')).first()

            if client is None:
                # Saving the row creates the schema and runs every tenant
                # migration inside it.
                client = self.Client(schema_name=slug.replace('-', '_'), name=slug)
                client.save()
                self.Domain.objects.create(domain='%s.example.com' % slug, tenant=client, is_primary=True)

            seconds.append(time.perf_counter() - started)
            self.tenant_ids.append(slug)

        return seconds

    def seed_tenant(self, tenant, articles, comments_per_article):
        with self.bind(tenant):
            authors = self.Author.objects.bulk_create(
                [self.Author(name='Author %d' % i) for i in range(AUTHORS_PER_TENANT)]
            )

            article_objects = self.Article.objects.bulk_create(
                [
                    self.Article(
                        author=authors[i % len(authors)],
                        title='Article %d' % i,
                        status=STATUSES[i % len(STATUSES)],
                        views=i,
                        published_at=BASE_DATETIME + datetime.timedelta(minutes=i),
                    )
                    for i in range(articles)
                ]
            )

            self.Comment.objects.bulk_create(
                [
                    self.Comment(article=article, body='Comment %d on %d' % (n, article.pk))
                    for article in article_objects
                    for n in range(comments_per_article)
                ]
            )

    def flush(self):
        from django_tenants.utils import schema_context

        for client in self.Client.objects.all():
            with schema_context(client.schema_name):
                self.Comment.objects.all().delete()
                self.Article.objects.all().delete()
                self.Author.objects.all().delete()

    @contextmanager
    def bind(self, tenant):
        from django_tenants.utils import schema_context

        # Entering the context issues ``SET search_path`` -- a round trip to
        # PostgreSQL that the row-level approaches do not make.
        with schema_context(tenant.replace('-', '_')):
            self.current = tenant
            yield

        self.current = None

    def articles(self):
        return self.Article.objects.all()

    def comments(self):
        return self.Comment.objects.all()

    def authors(self):
        return self.Author.objects.all()

    def new_article(self, author, title):
        return self.Article(
            author=author,
            title=title,
            status='published',
            views=0,
            published_at=BASE_DATETIME,
        )

    def new_comment(self, article, body):
        return self.Comment(article=article, body=body)

    def join_relation(self):
        return 'article'

    def plain_join_relation(self):
        return 'article'

    def cross_tenant_counts(self):
        from django_tenants.utils import schema_context

        results = []

        for tenant in self.tenant_ids:
            with schema_context(tenant.replace('-', '_')):
                results.append({'tenant': tenant, 'total': self.Article.objects.count()})

        return results

    def storage(self):
        return _storage(['tenant_app_article', 'tenant_app_comment'], every_schema=True)


#: Authors are a small dimension table in every approach; the interesting
#: volume is in articles and comments.
AUTHORS_PER_TENANT = 20


def _storage(tables, every_schema=False):
    """Sum table and index bytes for ``tables`` across one or all schemas."""
    from django.db import connection

    if every_schema:
        predicate = "n.nspname NOT IN ('pg_catalog', 'information_schema')"
    else:
        predicate = "n.nspname = 'public'"

    placeholders = ', '.join(['%s'] * len(tables))

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                COALESCE(SUM(pg_table_size(c.oid)), 0),
                COALESCE(SUM(pg_indexes_size(c.oid)), 0)
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname IN (%s) AND %s
            """
            % (placeholders, predicate),
            tables,
        )
        table_bytes, index_bytes = cursor.fetchone()

    return {'table_bytes': int(table_bytes), 'index_bytes': int(index_bytes)}


class TenantsLimitedAdapter(TenantsAdapter):
    """django-tenants with ``TENANT_LIMIT_SET_CALLS``: one ``SET`` per switch."""

    key = 'tenants_limited'
    label = 'django-tenants (limit_set_calls)'


ADAPTERS = {
    'shared': SharedAdapter,
    'manual': ManualAdapter,
    'tenants': TenantsAdapter,
    'tenants_limited': TenantsLimitedAdapter,
}


def get_adapter(key):
    return ADAPTERS[key]()
