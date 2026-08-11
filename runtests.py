#!/usr/bin/env python

import os
import sys
from typing import Any

import django
from django.conf import settings
from django.test.utils import get_runner


def run_tests(*args: str, **kwargs: Any) -> None:
    # ``--settings=tests.settings_swapped`` runs the same suite against a project
    # that replaced the organization and membership models. Falls back to the
    # environment, then to the defaults, so plain ``runtests.py`` is unchanged.
    settings_module = kwargs.pop('settings', None) or os.environ.get('DJANGO_SETTINGS_MODULE') or 'tests.settings'
    os.environ['DJANGO_SETTINGS_MODULE'] = str(settings_module)
    django.setup()
    TestRunner = get_runner(settings)
    test_runner = TestRunner(**kwargs)
    failures = test_runner.run_tests(list(args))
    sys.exit(bool(failures))


def process_kwargs(kwarg: str) -> tuple[str, str | bool]:
    if len(kwarg.split('=')) == 2:
        return (kwarg.split('=')[0], kwarg.split('=')[1])

    else:
        return (kwarg, True)


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    kwargs = dict(process_kwargs(a[2:]) for a in sys.argv[1:] if a.startswith('--'))

    run_tests(*args, **kwargs)
