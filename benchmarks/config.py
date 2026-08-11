"""Shared configuration for the benchmark suite.

Everything is read from the environment so the same code runs against a local
PostgreSQL, a container, or CI without editing settings modules.
"""

import os

PG_HOST = os.environ.get('BENCH_PG_HOST', 'localhost')
PG_PORT = os.environ.get('BENCH_PG_PORT', '55432')
PG_USER = os.environ.get('BENCH_PG_USER', 'postgres')
PG_PASSWORD = os.environ.get('BENCH_PG_PASSWORD', 'postgres')

#: One database per approach: the three schemas would otherwise collide, and
#: keeping them apart also keeps each approach's table statistics its own.
DATABASE_NAMES = {
    'shared': os.environ.get('BENCH_DB_SHARED', 'bench_shared'),
    'manual': os.environ.get('BENCH_DB_MANUAL', 'bench_manual'),
    'tenants': os.environ.get('BENCH_DB_TENANTS', 'bench_tenants'),
    'tenants_limited': os.environ.get('BENCH_DB_TENANTS_LIMITED', 'bench_tenants_limited'),
}

#: Defaults for the dataset. Overridable on the command line.
DEFAULT_TENANTS = 10
DEFAULT_ARTICLES_PER_TENANT = 2000
DEFAULT_COMMENTS_PER_ARTICLE = 3
DEFAULT_ITERATIONS = 200
DEFAULT_WARMUP = 20


def database(approach, engine='django.db.backends.postgresql'):
    return {
        'default': {
            'ENGINE': engine,
            'NAME': DATABASE_NAMES[approach],
            'USER': PG_USER,
            'PASSWORD': PG_PASSWORD,
            'HOST': PG_HOST,
            'PORT': PG_PORT,
            # The benchmark opens one connection and keeps it: connection setup
            # is not what is being measured, and a per-query reconnect would
            # dwarf the differences between the approaches.
            'CONN_MAX_AGE': None,
            'ATOMIC_REQUESTS': False,
            'AUTOCOMMIT': True,
            'OPTIONS': {},
            'TIME_ZONE': None,
            'CONN_HEALTH_CHECKS': False,
            'TEST': {},
        }
    }


def tenant_slug(index):
    return 'tenant-%03d' % index
