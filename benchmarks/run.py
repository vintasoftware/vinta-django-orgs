"""Run every approach and print a comparison.

    uv run python -m benchmarks.run
    uv run python -m benchmarks.run --tenants 50 --articles 5000 --iterations 500

Each approach runs in its own process against its own database, then the
results are collected into a Markdown report. See ``benchmarks/README.md``.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

from benchmarks import config

APPROACHES = ['shared', 'manual', 'tenants', 'tenants_limited']

RESULTS_DIR = os.path.join(os.path.dirname(__file__), 'results')


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--tenants', type=int, default=config.DEFAULT_TENANTS)
    parser.add_argument('--articles', type=int, default=config.DEFAULT_ARTICLES_PER_TENANT)
    parser.add_argument('--comments', type=int, default=config.DEFAULT_COMMENTS_PER_ARTICLE)
    parser.add_argument('--iterations', type=int, default=config.DEFAULT_ITERATIONS)
    parser.add_argument('--warmup', type=int, default=config.DEFAULT_WARMUP)
    parser.add_argument('--only', default='', help='comma-separated scenario keys')
    parser.add_argument(
        '--approaches',
        default=','.join(APPROACHES),
        help='comma-separated subset of %s' % ','.join(APPROACHES),
    )
    parser.add_argument(
        '--keep-db',
        action='store_true',
        help='reuse the existing databases instead of recreating them (setup timings become meaningless)',
    )
    parser.add_argument('--reuse-data', action='store_true', help='skip seeding; implies --keep-db')
    parser.add_argument('--out', default='', help='write the Markdown report here as well as to stdout')
    return parser.parse_args(argv)


def recreate_database(name):
    import psycopg

    dsn = 'host=%s port=%s user=%s password=%s dbname=postgres' % (
        config.PG_HOST,
        config.PG_PORT,
        config.PG_USER,
        config.PG_PASSWORD,
    )

    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % name)
        connection.execute('CREATE DATABASE "%s"' % name)


def ensure_database(name):
    import psycopg

    dsn = 'host=%s port=%s user=%s password=%s dbname=postgres' % (
        config.PG_HOST,
        config.PG_PORT,
        config.PG_USER,
        config.PG_PASSWORD,
    )

    with psycopg.connect(dsn, autocommit=True) as connection:
        exists = connection.execute('SELECT 1 FROM pg_database WHERE datname = %s', (name,)).fetchone()

        if not exists:
            connection.execute('CREATE DATABASE "%s"' % name)


def run_approach(approach, args):
    handle, path = tempfile.mkstemp(suffix='.json', prefix='bench-%s-' % approach)
    os.close(handle)

    command = [
        sys.executable,
        '-m',
        'benchmarks.runner',
        '--approach',
        approach,
        '--tenants',
        str(args.tenants),
        '--articles',
        str(args.articles),
        '--comments',
        str(args.comments),
        '--iterations',
        str(args.iterations),
        '--warmup',
        str(args.warmup),
        '--out',
        path,
    ]

    if args.only:
        command += ['--only', args.only]

    if args.reuse_data:
        command.append('--reuse-data')

    started = time.perf_counter()
    subprocess.run(command, check=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    elapsed = time.perf_counter() - started

    with open(path) as file:
        results = json.load(file)

    os.unlink(path)
    results['wall_seconds'] = elapsed
    return results


def environment():
    import django
    import psycopg

    dsn = 'host=%s port=%s user=%s password=%s dbname=postgres' % (
        config.PG_HOST,
        config.PG_PORT,
        config.PG_USER,
        config.PG_PASSWORD,
    )

    with psycopg.connect(dsn) as connection:
        server_version = connection.execute('SHOW server_version').fetchone()[0]

    try:
        from importlib.metadata import version

        tenants_version = version('django-tenants')
    except Exception:
        tenants_version = 'unknown'

    return {
        'python': sys.version.split()[0],
        'django': django.get_version(),
        'django_tenants': tenants_version,
        'postgresql': server_version,
        'platform': sys.platform,
    }


# -- reporting ---------------------------------------------------------------


def format_bytes(value):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if value < 1024 or unit == 'GB':
            return '%.1f %s' % (value, unit)
        value /= 1024


def table(headers, rows):
    widths = [len(header) for header in headers]

    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    lines = [
        '| ' + ' | '.join(header.ljust(widths[index]) for index, header in enumerate(headers)) + ' |',
        '| ' + ' | '.join('-' * widths[index] for index in range(len(headers))) + ' |',
    ]

    for row in rows:
        lines.append('| ' + ' | '.join(cell.ljust(widths[index]) for index, cell in enumerate(row)) + ' |')

    return '\n'.join(lines)


def report(results, args):
    from benchmarks.scenarios import SCENARIOS

    approaches = [result['approach'] for result in results]
    by_approach = {result['approach']: result for result in results}
    dataset = results[0]['dataset']
    env = environment()

    out = []
    out.append('# Multi-tenancy query benchmark\n')
    out.append(
        'Python %(python)s, Django %(django)s, django-tenants %(django_tenants)s, '
        'PostgreSQL %(postgresql)s, %(platform)s.\n' % env
    )
    out.append(
        '%d tenants, %d articles and %d comments per tenant '
        '(%s articles and %s comments in total per approach). '
        '%d timed iterations per scenario after %d warm-up calls; medians reported.\n'
        % (
            dataset['tenants'],
            dataset['articles_per_tenant'],
            dataset['articles_per_tenant'] * dataset['comments_per_article'],
            '{:,}'.format(dataset['total_articles']),
            '{:,}'.format(dataset['total_comments']),
            args.iterations,
            args.warmup,
        )
    )

    out.append('\n## Median time per operation (ms)\n')

    headers = ['Scenario'] + [by_approach[a]['label'] for a in approaches]
    baseline = 'tenants' if 'tenants' in by_approach else approaches[0]

    if 'shared' in by_approach and baseline != 'shared':
        headers.append('shared vs %s' % baseline)

    rows = []

    for scenario in SCENARIOS:
        if not any(scenario.key in by_approach[a]['scenarios'] for a in approaches):
            continue

        row = [scenario.key]

        for approach in approaches:
            stats = by_approach[approach]['scenarios'].get(scenario.key)
            row.append('%.3f' % stats['median_ms'] if stats else '--')

        if len(headers) > len(approaches) + 1:
            shared_stats = by_approach['shared']['scenarios'].get(scenario.key)
            base_stats = by_approach[baseline]['scenarios'].get(scenario.key)

            if shared_stats and base_stats and base_stats['median_ms']:
                ratio = shared_stats['median_ms'] / base_stats['median_ms']
                row.append('%.2fx' % ratio)
            else:
                row.append('--')

        rows.append(row)

    out.append(table(headers, rows))

    out.append('\n## Queries issued per operation\n')

    query_rows = []

    for scenario in SCENARIOS:
        if not any(scenario.key in by_approach[a]['scenarios'] for a in approaches):
            continue

        row = [scenario.key]

        for approach in approaches:
            stats = by_approach[approach]['scenarios'].get(scenario.key)
            row.append(str(stats['query_count']) if stats else '--')

        query_rows.append(row)

    out.append(table(['Scenario'] + [by_approach[a]['label'] for a in approaches], query_rows))

    out.append('\n## Setup cost\n')

    setup_rows = []

    for approach in approaches:
        setup = by_approach[approach]['setup']
        setup_rows.append(
            [
                by_approach[approach]['label'],
                '%.2f' % setup['migrate_seconds'],
                '%.3f' % setup['create_tenant_seconds_each'],
                '%.2f' % setup['seed_seconds'] if setup['seed_seconds'] is not None else '--',
            ]
        )

    out.append(
        table(
            ['Approach', 'Migrate (s)', 'Per tenant (s)', 'Seed data (s)'],
            setup_rows,
        )
    )

    out.append('\n## Storage (article + comment tables, all schemas)\n')

    storage_rows = []

    for approach in approaches:
        storage = by_approach[approach]['storage']
        storage_rows.append(
            [
                by_approach[approach]['label'],
                format_bytes(storage['table_bytes']),
                format_bytes(storage['index_bytes']),
                format_bytes(storage['table_bytes'] + storage['index_bytes']),
            ]
        )

    out.append(table(['Approach', 'Tables', 'Indexes', 'Total'], storage_rows))

    out.append('\n## Scenarios\n')

    for scenario in SCENARIOS:
        out.append('- **%s** -- %s' % (scenario.key, scenario.description))

    out.append('\n## Sample SQL\n')

    for scenario_key in ['point_lookup', 'join_plain', 'join_safe']:
        for approach in approaches:
            stats = by_approach[approach]['scenarios'].get(scenario_key)

            if stats and stats['sample_sql']:
                out.append('`%s` / %s:\n' % (scenario_key, by_approach[approach]['label']))
                out.append('```sql\n%s\n```\n' % stats['sample_sql'])

    return '\n'.join(out)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    approaches = [a for a in args.approaches.split(',') if a]

    for approach in approaches:
        name = config.DATABASE_NAMES[approach]

        if args.keep_db or args.reuse_data:
            ensure_database(name)
        else:
            recreate_database(name)

    results = [run_approach(approach, args) for approach in approaches]

    os.makedirs(RESULTS_DIR, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')

    with open(os.path.join(RESULTS_DIR, 'results-%s.json' % stamp), 'w') as handle:
        json.dump({'environment': environment(), 'results': results}, handle, indent=2)

    markdown = report(results, args)
    print(markdown)

    if args.out:
        with open(args.out, 'w') as handle:
            handle.write(markdown)

    return 0


if __name__ == '__main__':
    sys.exit(main())
