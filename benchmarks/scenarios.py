"""The workloads, written once against the adapter API.

Each scenario declares how to build its timed callable from an adapter. The
callable is what gets timed, so anything that only sets the scenario up --
picking primary keys, fetching an author to point new rows at -- happens in
``build`` and stays out of the measurement.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from django.db.models import Avg, Count, F


@dataclass
class Scenario:
    key: str
    label: str
    description: str
    #: ``build(adapter, state) -> callable`` (optionally a ``(callable, cleanup)`` pair).
    build: Callable
    #: False for scenarios that do their own tenant binding.
    bound: bool = True
    #: Multiplier on the iteration count -- writes are slower and grow the
    #: dataset, so they run fewer times.
    weight: float = 1.0
    #: Approaches this scenario does not apply to.
    skip_for: tuple = field(default_factory=tuple)


def _cycle(values):
    """Endless cycle over ``values`` without importing itertools per call."""
    index = 0

    while True:
        yield values[index % len(values)]
        index += 1


def _article_pks(adapter, limit=500):
    return list(adapter.articles().order_by('id').values_list('pk', flat=True)[:limit])


# -- reads -------------------------------------------------------------------


def build_point_lookup(adapter, state):
    pks = _cycle(_article_pks(adapter))
    articles = adapter.articles

    def run():
        return articles().get(pk=next(pks))

    return run


def build_list_recent(adapter, state):
    articles = adapter.articles

    def run():
        return list(articles().order_by('-published_at')[:50])

    return run


def build_filter_count(adapter, state):
    articles = adapter.articles

    def run():
        return articles().filter(status='published').count()

    return run


def build_filter_page(adapter, state):
    articles = adapter.articles

    def run():
        return list(articles().filter(status='published').order_by('-published_at')[:50])

    return run


def build_aggregate(adapter, state):
    articles = adapter.articles

    def run():
        return articles().aggregate(total=Count('id'), average_views=Avg('views'))

    return run


def build_join_plain(adapter, state):
    comments = adapter.comments
    relation = adapter.plain_join_relation()

    def run():
        return list(comments().select_related(relation).order_by('id')[:50])

    return run


def build_join_safe(adapter, state):
    comments = adapter.comments
    relation = adapter.join_relation()

    def run():
        return list(comments().select_related(relation).order_by('id')[:50])

    return run


def build_agg_join_plain(adapter, state):
    comments = adapter.comments
    lookup = '%s__views' % adapter.plain_join_relation()

    def run():
        return comments().aggregate(average=Avg(lookup))

    return run


def build_agg_join_safe(adapter, state):
    """The same aggregate through the organization-safe relation.

    Unbounded joins are where the safe relation pays for itself: the
    organization equality lets PostgreSQL restrict the far side of the join to
    one tenant, where a plain foreign key has to consider every tenant's rows.
    """
    comments = adapter.comments
    lookup = '%s__views' % adapter.join_relation()

    def run():
        return comments().aggregate(average=Avg(lookup))

    return run


def build_join_filter(adapter, state):
    comments = adapter.comments
    lookup = '%s__status' % adapter.join_relation()

    def run():
        return list(comments().filter(**{lookup: 'published'}).order_by('id')[:50])

    return run


# -- writes ------------------------------------------------------------------


def build_insert(adapter, state):
    author = adapter.authors().first()
    created = []

    def run():
        article = adapter.new_article(author, 'Inserted')
        article.save()
        created.append(article.pk)

    def cleanup():
        adapter.articles().filter(pk__in=created).delete()
        created.clear()

    return run, cleanup


def build_bulk_insert(adapter, state):
    author = adapter.authors().first()
    created = []

    def run():
        articles = [adapter.new_article(author, 'Bulk %d' % i) for i in range(100)]
        adapter.articles().bulk_create(articles)
        created.extend(article.pk for article in articles)

    def cleanup():
        adapter.articles().filter(pk__in=created).delete()
        created.clear()

    return run, cleanup


def build_update(adapter, state):
    pks = _cycle(_article_pks(adapter, limit=100))
    articles = adapter.articles

    def run():
        return articles().filter(pk=next(pks)).update(views=F('views') + 1)

    return run


# -- tenancy-specific --------------------------------------------------------


def build_tenant_switch(adapter, state):
    """Bind a different tenant and read one row.

    A contextvar assignment against a ``SET search_path`` round trip: the cost
    a request pays before it has done any work of its own.
    """
    tenants = _cycle(adapter.tenant_ids)

    def run():
        with adapter.bind(next(tenants)):
            return list(adapter.articles().order_by('-published_at')[:1])

    return run


def build_cross_tenant_report(adapter, state):
    """Count articles per tenant across the whole installation."""

    def run():
        return adapter.cross_tenant_counts()

    return run


SCENARIOS = [
    Scenario(
        'point_lookup',
        'Point lookup by primary key',
        'Fetch one article by pk. The shared-schema approaches also filter on the tenant column.',
        build_point_lookup,
    ),
    Scenario(
        'list_recent',
        'List 50 most recent articles',
        'ORDER BY published_at DESC LIMIT 50 -- the archetypal list page.',
        build_list_recent,
    ),
    Scenario(
        'filter_count',
        'Count published articles',
        "COUNT over roughly a third of one tenant's rows.",
        build_filter_count,
    ),
    Scenario(
        'filter_page',
        'Filter + sort + paginate',
        'status = published, ordered by published_at, first 50.',
        build_filter_page,
    ),
    Scenario(
        'aggregate',
        'Aggregate over a tenant',
        'COUNT and AVG across every article the tenant owns.',
        build_aggregate,
    ),
    Scenario(
        'join_plain',
        'Join via plain foreign key',
        'select_related over a normal FK: the join matches on the key alone.',
        build_join_plain,
    ),
    Scenario(
        'join_safe',
        'Join via organization-safe relation',
        'select_related over an OrganizationSafeForeignKey: the join also matches on the tenant column. '
        'Only this library has a second relation to compare against; elsewhere this is the same query as join_plain.',
        build_join_safe,
        skip_for=('manual', 'tenants', 'tenants_limited'),
    ),
    Scenario(
        'agg_join_plain',
        'Aggregate across a join, plain foreign key',
        'AVG over every comment joined to its article -- an unbounded join, no LIMIT.',
        build_agg_join_plain,
    ),
    Scenario(
        'agg_join_safe',
        'Aggregate across a join, organization-safe relation',
        'The same unbounded aggregate through OrganizationSafeForeignKey. The organization equality lets '
        "PostgreSQL restrict the far side to one tenant instead of scanning every tenant's rows.",
        build_agg_join_safe,
        skip_for=('manual', 'tenants', 'tenants_limited'),
    ),
    Scenario(
        'join_filter',
        'Filter across a join',
        'Comments whose article is published -- a join plus a predicate on the far side.',
        build_join_filter,
    ),
    Scenario(
        'insert',
        'Insert one article',
        'A single INSERT through the normal save() path.',
        build_insert,
        weight=0.5,
    ),
    Scenario(
        'bulk_insert',
        'Bulk insert 100 articles',
        'bulk_create of 100 rows.',
        build_bulk_insert,
        weight=0.1,
    ),
    Scenario(
        'update',
        'Update one article',
        'UPDATE … SET views = views + 1 WHERE pk = …',
        build_update,
        weight=0.5,
    ),
    Scenario(
        'tenant_switch',
        'Switch tenant and read',
        'Bind a different tenant, then read a single row. Prices the switch itself.',
        build_tenant_switch,
        bound=False,
    ),
    Scenario(
        'cross_tenant_report',
        'Count articles per tenant, all tenants',
        'One GROUP BY for a shared schema; one query per schema for schema-per-tenant.',
        build_cross_tenant_report,
        bound=False,
        weight=0.25,
    ),
]
