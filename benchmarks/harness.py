"""Timing, statistics and query counting."""

import statistics
import time


def percentile(samples, fraction):
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def measure(run, iterations, warmup):
    """Time ``run`` and return per-call statistics in milliseconds.

    Warm-up calls are discarded: the first call of a scenario pays for
    PostgreSQL planning the statement, Django building the queryset's SQL and
    the connection's first use, none of which repeat.
    """
    for _ in range(warmup):
        run()

    samples = []

    for _ in range(iterations):
        started = time.perf_counter()
        run()
        samples.append(time.perf_counter() - started)

    mean = statistics.fmean(samples)

    return {
        'iterations': iterations,
        'min_ms': min(samples) * 1000,
        'median_ms': statistics.median(samples) * 1000,
        'mean_ms': mean * 1000,
        'p95_ms': percentile(samples, 0.95) * 1000,
        'max_ms': max(samples) * 1000,
        'stdev_ms': (statistics.stdev(samples) * 1000) if len(samples) > 1 else 0.0,
        'ops_per_second': (1 / mean) if mean else None,
    }


def count_queries(run):
    """Run ``run`` once with the debug cursor on and return the SQL it issued.

    Kept out of the timed loop: the debug cursor records every statement, which
    is overhead the measurement should not carry.
    """
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as captured:
        run()

    return [query['sql'] for query in captured.captured_queries]
