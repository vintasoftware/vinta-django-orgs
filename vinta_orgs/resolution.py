"""Values shared by organization-selection integration points."""

from typing import Final, TypeAlias


class _UnresolvedOrganization:
    """Type of the public unresolved-organization singleton."""

    __slots__ = ()

    def __repr__(self) -> str:
        return 'UNRESOLVED_ORGANIZATION'


UNRESOLVED_ORGANIZATION: Final = _UnresolvedOrganization()
"""A supplied organization identifier that matched no organization."""

OrganizationSelection: TypeAlias = str | _UnresolvedOrganization | None
