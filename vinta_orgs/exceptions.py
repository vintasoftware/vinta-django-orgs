from typing import Any

from django.core.exceptions import BadRequest, PermissionDenied


class OrganizationNotFoundError(Exception):
    def __init__(self, message: str = "Organization with this slug couldn't be found", errors: Any = None) -> None:
        super().__init__(message)


class AmbiguousOrganizationError(BadRequest):
    """The caller belongs to several organizations and named none of them.

    Raised by :func:`vinta_orgs.helpers.memberships.resolve_organization_for_user`
    and by the retrievers built on it. Picking one of them -- the oldest
    membership, say -- is the failure this exists to prevent: the request then
    reads and writes an organization the caller never asked for, and which one
    it is depends on the order rows happened to be created in.

    Subclasses Django's ``BadRequest`` so an unhandled one is a 400 rather than
    a 500 on the plain Django path. On the DRF path
    :class:`vinta_orgs.drf.OrganizationScopedAPIViewMixin` translates it into a
    ``ValidationError``, so the body is rendered by the content negotiation the
    rest of the API uses.
    """

    def __init__(self, message: str = 'Several organizations match this request; name one explicitly.') -> None:
        super().__init__(message)


class OrganizationAccessDeniedError(PermissionDenied):
    """The caller named an organization they hold no active membership in.

    Distinct from :class:`OrganizationNotFoundError`, which means the slug
    matches no organization at all. Both are refusals; only this one is about
    the caller.

    Subclasses Django's ``PermissionDenied``, which both Django's own handler
    and DRF's ``exception_handler`` already turn into a 403 -- so a project that
    never catches it still refuses the request rather than serving another
    organization's data.
    """

    def __init__(self, message: str = 'You are not an active member of this organization.') -> None:
        super().__init__(message)
