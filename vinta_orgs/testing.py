"""Test helpers for the one hazard this library's setup creates on its own.

Seeded groups are the recommended way to express organization roles: a data
migration creates ``organization_owner`` (see
:func:`vinta_orgs.seeding.create_default_organization_groups`) and
whatever else the project needs, memberships are put in them, and every
permission check reads a permission rather than a role name.

That works until a test flushes the database.

A test that runs in a real transaction -- ``TransactionTestCase``, or pytest's
``@pytest.mark.django_db(transaction=True)`` -- *flushes* every table when it
finishes. ``flush`` re-emits ``post_migrate``, so ``django_content_type`` and
``auth_permission`` are rebuilt by Django's own receivers. Nothing rebuilds rows
a **data migration** wrote. The groups, and every ``auth_group_permissions`` row
hanging off them, are gone for the rest of that worker's session.

What that looks like is not "a missing group". Both test runners group
transactional tests together and run them after the rest, so only the first one
sees a seeded database; from then on every membership built by a test silently
holds no permission at all, and the failures land in whichever unrelated module
happens to assert on a permission next. It reads as flakiness, or as parallel
load, and it is neither.

The repair belongs at *setup*, not teardown: the flush happens in the test
runner's own finalizer, after any teardown hook a test could install, so there
is no hook late enough. Re-establishing the invariant before each test is both
sufficient and the only reachable point.

Three ways to install it, depending on the runner:

``unittest`` / Django's runner
    Mix :class:`SeededOrganizationGroupsMixin` into the ``TransactionTestCase``
    subclasses, or into a project-wide base test case.

pytest
    Add ``pytest_plugins = ['vinta_orgs.testing']`` to the root ``conftest.py``;
    the autouse :func:`seeded_organization_groups` fixture below does the rest.

By hand
    Call :func:`reseed_organization_groups` wherever the project prefers.

Seed *head* state, not the migration's. If a project seeds more groups than the
one this library ships, point ``ORGANIZATION_GROUP_SEEDERS`` at the callables
that build them -- the same ones the data migration calls -- rather than
copying their contents here. A data migration is entitled to stop describing
what the code now expects; this must not.

A seeder runs with **no organization bound**: it runs before the test that
would bind one. Groups are global rows, so this is only a constraint on a
project that has hung organization-scoped state off ``auth.Group`` -- which then
has to bind an organization itself, inside the seeder.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from vinta_orgs.seeding import create_default_organization_groups

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from django.contrib.auth.models import Group

__all__ = [
    'SeededOrganizationGroupsMixin',
    'organization_group_seeders',
    'reseed_organization_groups',
]


def organization_group_seeders() -> list[Callable[[], list[Group]]]:
    """The callables that build the seeded groups, head state included.

    Defaults to this library's own. Override with the
    ``ORGANIZATION_GROUP_SEEDERS`` key -- a list of import paths -- so a project
    that seeds more groups repairs all of them::

        SHARED_SCHEMA_ORGANIZATIONS = {
            'ORGANIZATION_GROUP_SEEDERS': [
                'vinta_orgs.seeding.create_default_organization_groups',
                'myproject.organizations.groups.create_role_groups',
            ],
        }
    """
    from vinta_orgs.settings import get_setting
    from vinta_orgs.utils import import_from_string

    configured = get_setting('ORGANIZATION_GROUP_SEEDERS')

    if not configured:
        return [create_default_organization_groups]

    return [import_from_string(path) for path in configured]


def reseed_organization_groups() -> list[Group]:
    """Recreate the seeded groups and their permissions. Idempotent, and cheap.

    Additive rather than authoritative: it does not revoke a permission a test
    attached on purpose. When nothing was destroyed -- the ~99% case, since only
    a transactional test destroys anything -- each seeder costs one
    ``get_or_create`` that finds its row and stops, which is why this runs
    unguarded rather than behind a "are they still there?" query that would cost
    the same.

    A seeder must be safe to call twice, and must attach its permissions on the
    run that creates the group. The one this library ships is: group presence
    and permission rows are removed together (a flush removes both) and restored
    together, so "the group exists" implies its permissions do.
    """
    groups: list[Group] = []

    for seeder in organization_group_seeders():
        groups.extend(seeder())

    return groups


class SeededOrganizationGroupsMixin:
    """Guarantee the seeded groups exist before each test in the class.

    Mix into a ``TransactionTestCase`` (or a project's base test case) *before*
    the ``TestCase`` class, so this ``setUp`` runs::

        class MyFlowTests(SeededOrganizationGroupsMixin, TransactionTestCase):
            ...
    """

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        reseed_organization_groups()


# The fixture below is only defined when pytest is importable, so this module
# stays importable from a project that runs its tests any other way -- the
# reseed function and the mixin above are the parts that do not need it.
try:  # pragma: no cover - depends on the consumer's test runner
    import pytest

    PYTEST_AVAILABLE = True
except ImportError:  # pragma: no cover
    PYTEST_AVAILABLE = False


if PYTEST_AVAILABLE:  # pragma: no cover - exercised only under pytest
    #: The pytest-django entry points that give a test a database. A test naming
    #: any of them -- or carrying the ``django_db`` marker, or subclassing
    #: ``TransactionTestCase`` -- can be reseeded; anything else has database
    #: access blocked and must be left alone, or the fixture turns "this test
    #: touches no database" into an error.
    _DATABASE_FIXTURES = frozenset(
        {
            'db',
            'transactional_db',
            'django_db_reset_sequences',
            'django_db_serialized_rollback',
            'live_server',
        }
    )

    def _test_uses_the_database(request: Any) -> bool:
        if request.node.get_closest_marker('django_db') is not None:
            return True

        if _DATABASE_FIXTURES & set(request.fixturenames):
            return True

        from django.test import TransactionTestCase

        cls = getattr(request.node, 'cls', None)

        return isinstance(cls, type) and issubclass(cls, TransactionTestCase)

    @pytest.fixture(autouse=True)
    def seeded_organization_groups(request: Any) -> Iterator[None]:
        """Reseed the organization groups before any test that has a database.

        Autouse, because the consumers are unrelated both to each other and to
        the test that destroyed the state -- the permission classes, whatever
        assigns groups to memberships, the ``finally`` of any test that steps
        migrations backwards. Repairing it per consumer is what lets one root
        cause surface repeatedly wearing different symptoms.
        """
        if not _test_uses_the_database(request):
            yield
            return

        # Force the database up first. Autouse fixtures declared in a plugin run
        # *before* the ``db`` / ``transactional_db`` fixture a test requests by
        # name, so without this the reseed would hit pytest-django's access
        # blocker. pytest-django's own ``_django_db_marker`` does exactly this.
        request.getfixturevalue('_django_db_helper')

        reseed_organization_groups()

        yield
