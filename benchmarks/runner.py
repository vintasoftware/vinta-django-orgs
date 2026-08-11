"""Run the benchmark for a single approach and write its results as JSON.

One approach per process on purpose: the three settings modules disagree about
the database engine, the installed apps and the routers, and django-tenants
patches the connection. Anything sharing a process would be measuring the
compromise rather than the approach.

Normally driven by :mod:`benchmarks.run`; runnable on its own for debugging::

    uv run python -m benchmarks.runner --approach shared --iterations 50
"""

import argparse
import contextlib
import io
import json
import os
import sys
import time

from benchmarks import config


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approach', required=True, choices=['shared', 'manual', 'tenants', 'tenants_limited'])
    parser.add_argument('--tenants', type=int, default=config.DEFAULT_TENANTS)
    parser.add_argument('--articles', type=int, default=config.DEFAULT_ARTICLES_PER_TENANT)
    parser.add_argument('--comments', type=int, default=config.DEFAULT_COMMENTS_PER_ARTICLE)
    parser.add_argument('--iterations', type=int, default=config.DEFAULT_ITERATIONS)
    parser.add_argument('--warmup', type=int, default=config.DEFAULT_WARMUP)
    parser.add_argument('--only', default='', help='comma-separated scenario keys to run')
    parser.add_argument('--reuse-data', action='store_true', help='skip seeding and use whatever is in the database')
    parser.add_argument('--out', default='', help='write JSON results here instead of stdout')
    return parser.parse_args(argv)


def setup_django(approach):
    import django

    os.environ['DJANGO_SETTINGS_MODULE'] = 'benchmarks.settings_%s' % approach
    django.setup()


def make_migrations(approach):
    """Generate the benchmark apps' migrations if they are not there yet.

    They are derived from the models and gitignored: keeping them checked in
    would be one more thing to remember to regenerate whenever a benchmark
    model changes.
    """
    from django.core.management import call_command

    labels = {
        'shared': ['shared_app'],
        'manual': ['manual_app'],
        'tenants': ['tenants_public', 'tenant_app'],
        'tenants_limited': ['tenants_public', 'tenant_app'],
    }[approach]

    from django.apps import apps

    for label in labels:
        # Regenerated from scratch every run: a stale 0001 left over from an
        # earlier model would otherwise turn a changed index into an 0002 that
        # only some of the approaches have.
        directory = os.path.join(os.path.dirname(apps.get_app_config(label).module.__file__), 'migrations')

        for name in os.listdir(directory):
            if name[0].isdigit() and name.endswith('.py'):
                os.unlink(os.path.join(directory, name))

    for label in labels:
        call_command('makemigrations', label, verbosity=0, interactive=False)


def seed(adapter, args):
    """Create the schema, the tenants and the rows. Returns the setup timings."""
    timings = {}

    started = time.perf_counter()

    # django-tenants prints a migration banner per schema regardless of
    # verbosity, which would bury the results; progress goes to stderr instead.
    with contextlib.redirect_stdout(io.StringIO()):
        make_migrations(args.approach)
        adapter.migrate()

    timings['migrate_seconds'] = time.perf_counter() - started

    with contextlib.redirect_stdout(io.StringIO()):
        tenant_seconds = adapter.create_tenants(args.tenants)
    timings['create_tenants_seconds'] = sum(tenant_seconds)
    timings['create_tenant_seconds_each'] = sum(tenant_seconds) / len(tenant_seconds)

    if args.reuse_data:
        timings['seed_seconds'] = None
        analyze()
        return timings

    adapter.flush()

    started = time.perf_counter()

    for tenant in adapter.tenant_ids:
        adapter.seed_tenant(tenant, args.articles, args.comments)

    timings['seed_seconds'] = time.perf_counter() - started

    analyze()

    return timings


def analyze():
    """Refresh planner statistics for every table in the database.

    Without this the run races autovacuum: PostgreSQL plans against whatever
    statistics happen to exist, and a sequential scan chosen because a table
    still looks empty would be read as the approach being slow.
    """
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute('ANALYZE')


def run_scenarios(adapter, args):
    from benchmarks.harness import count_queries, measure
    from benchmarks.scenarios import SCENARIOS

    only = {key for key in args.only.split(',') if key}
    # The middle tenant, so the rows read are neither the first nor the last
    # ones inserted -- a shared table's physical ordering would otherwise
    # flatter whichever tenant was seeded first.
    tenant = adapter.tenant_ids[len(adapter.tenant_ids) // 2]
    results = {}

    for scenario in SCENARIOS:
        if only and scenario.key not in only:
            continue

        if args.approach in scenario.skip_for:
            continue

        iterations = max(1, int(args.iterations * scenario.weight))
        warmup = max(1, int(args.warmup * scenario.weight))

        if scenario.bound:
            with adapter.bind(tenant):
                results[scenario.key] = _run_one(scenario, adapter, iterations, warmup, measure, count_queries)
        else:
            results[scenario.key] = _run_one(scenario, adapter, iterations, warmup, measure, count_queries)

        print(
            '  %-22s %8.3f ms  (%d queries)'
            % (scenario.key, results[scenario.key]['median_ms'], results[scenario.key]['query_count']),
            file=sys.stderr,
        )

    return results


def _run_one(scenario, adapter, iterations, warmup, measure, count_queries):
    built = scenario.build(adapter, {})
    run, cleanup = built if isinstance(built, tuple) else (built, None)

    stats = measure(run, iterations, warmup)
    queries = count_queries(run)

    if cleanup is not None:
        cleanup()

    stats['query_count'] = len(queries)
    stats['sample_sql'] = queries[0] if queries else None
    stats['label'] = scenario.label
    stats['description'] = scenario.description

    return stats


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    setup_django(args.approach)

    from benchmarks.adapters import get_adapter

    print('[%s] setting up' % args.approach, file=sys.stderr)
    adapter = get_adapter(args.approach)
    timings = seed(adapter, args)

    print('[%s] running scenarios' % args.approach, file=sys.stderr)
    results = {
        'approach': args.approach,
        'label': adapter.label,
        'dataset': {
            'tenants': args.tenants,
            'articles_per_tenant': args.articles,
            'comments_per_article': args.comments,
            'total_articles': args.tenants * args.articles,
            'total_comments': args.tenants * args.articles * args.comments,
        },
        'setup': timings,
        'storage': adapter.storage(),
        'scenarios': run_scenarios(adapter, args),
    }

    payload = json.dumps(results, indent=2)

    if args.out:
        with open(args.out, 'w') as handle:
            handle.write(payload)
    else:
        print(payload)

    return 0


if __name__ == '__main__':
    sys.exit(main())
