"""Type-aware factories for tests that run with default and swapped models."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from vinta_orgs.helpers.organizations import create_organization as _create_organization

if TYPE_CHECKING:
    # mypy runs against tests.settings, while runtime also exercises
    # tests.settings_swapped. Centralize that unavoidable test-only boundary
    # instead of weakening every model assignment with cast(Any, ...).
    from vinta_orgs.models import Organization


def create_organization(*args: Any, **kwargs: Any) -> Organization:
    return cast('Organization', _create_organization(*args, **kwargs))
