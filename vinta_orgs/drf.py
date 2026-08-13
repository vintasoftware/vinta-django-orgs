"""Organization resolution for DRF views, at a point where the user is known.

:class:`vinta_orgs.middleware.OrganizationMiddleware` resolves the organization
at Django-middleware time, which is *before* DRF authentication runs. With
session authentication that is fine -- ``AuthenticationMiddleware`` has already
put a lazy user on the request. With token, JWT or any other DRF authentication
class it is not: ``request.user`` at middleware time is ``AnonymousUser``, and
the credential that says who the caller is has not been looked at yet. A
retriever that needs the user -- which is every retriever that verifies
membership -- therefore cannot work there at all.

:class:`OrganizationScopedAPIViewMixin` moves the resolution into the one seam
between "``request.user`` is real" and "``check_permissions`` runs", and binds
the result for the rest of the request. Add it to your base viewset::

    from rest_framework import viewsets
    from vinta_orgs.drf import OrganizationScopedAPIViewMixin

    class BaseViewSet(OrganizationScopedAPIViewMixin, viewsets.ModelViewSet):
        pass

After it has run, every request carries:

``request.organization``
    The resolved organization, or ``None``.
``request.organization_membership``
    The membership it was resolved from, or ``None``.

and the organization is bound to the context every scoped manager reads, so
``MyModel.objects`` inside the view answers for it.

The middleware may stay in ``MIDDLEWARE`` alongside this -- it resolves the
non-DRF surface (the admin, server-rendered views), and this mixin's binding
replaces its own for the duration of the view, restoring it on the way out.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from rest_framework.exceptions import PermissionDenied, ValidationError

from vinta_orgs.exceptions import AmbiguousOrganizationError, OrganizationAccessDeniedError
from vinta_orgs.helpers.memberships import resolve_membership_for_user
from vinta_orgs.settings import get_setting
from vinta_orgs.state import OrganizationToken, reset_current_organization, set_current_organization

if TYPE_CHECKING:
    from django.http import HttpResponse
    from rest_framework.request import Request

    from vinta_orgs.models import Organization, OrganizationMembership


class OrganizationScopedAPIViewMixin:
    """Resolve, stash and bind the request's organization after DRF authentication.

    Mix into an ``APIView`` or a viewset -- before the DRF base class, so that
    :meth:`perform_authentication` and :meth:`dispatch` below win.
    """

    #: When True, the two refusals in the resolution table are suppressed and
    #: the organization resolves to ``None`` instead: a caller with several
    #: memberships and no header is not answered 400, and a header naming an
    #: organization they do not belong to is not answered 403.
    #:
    #: This is for the endpoints that have to work *before* an organization is
    #: selected -- the organization switcher listing what a caller may select,
    #: onboarding, accepting an invitation. Those views must then be written
    #: against an unbound context; under ``STRICT_ORGANIZATION_FILTER`` a scoped
    #: read from one raises rather than quietly returning nothing.
    organization_resolution_optional: bool = False

    #: Per-action opt-out, for a viewset where most actions require an
    #: organization and one does not::
    #:
    #:     class OrganizationViewSet(BaseViewSet):
    #:         organization_optional_actions = ('mine',)
    #:
    #: ``self.action`` is set by ``ViewSetMixin.initialize_request``, which runs
    #: before ``initial()``, so it is always current by the time this is read.
    organization_optional_actions: tuple[str, ...] = ()

    #: Set by :meth:`bind_organization`, consumed by :meth:`unbind_organization`.
    #: A DRF view instance is built per request -- ``APIView.as_view`` constructs
    #: ``cls(**initkwargs)`` inside the view closure -- so this is request state
    #: despite living on ``self``.
    _organization_token: OrganizationToken | None = None

    def is_organization_resolution_optional(self) -> bool:
        """Whether the refusals are suppressed for this particular request."""
        if self.organization_resolution_optional:
            return True

        action = getattr(self, 'action', None)

        return action is not None and action in self.organization_optional_actions

    def get_organization_slug(self, request: Request) -> str | None:
        """What the caller named, if anything. Override to read it from elsewhere.

        Reads the ``ORGANIZATION_HTTP_HEADER`` header, so a project that
        selects the organization with a URL segment or a query parameter
        overrides this one method rather than the resolution around it.
        """
        header: str | None = request.headers.get(get_setting('ORGANIZATION_HTTP_HEADER'))
        return header

    def resolve_organization(self, request: Request) -> None:
        """Resolve the organization and stash it on the request.

        Extracted from :meth:`perform_authentication` so tests can call it in
        isolation and subclasses can extend it without reimplementing the
        ordering around it. It touches nothing but the request: in particular it
        does **not** bind the organization, because only a caller inside
        ``dispatch`` has the ``finally`` that releases the binding again.

        The two package exceptions are translated into their DRF equivalents
        here rather than left to propagate. ``OrganizationAccessDeniedError``
        would already be answered 403 by DRF's handler, since it subclasses
        Django's ``PermissionDenied``; ``AmbiguousOrganizationError`` would fall
        through to Django's own ``BadRequest`` handling and be answered with an
        HTML 400 in the middle of a JSON API.
        """
        membership: OrganizationMembership | None

        try:
            membership = resolve_membership_for_user(
                cast('Any', getattr(request, 'user', None)),
                self.get_organization_slug(request),
                strict=not self.is_organization_resolution_optional(),
            )
        except AmbiguousOrganizationError as exc:
            raise ValidationError({'detail': str(exc)}) from exc
        except OrganizationAccessDeniedError as exc:
            raise PermissionDenied(str(exc)) from exc

        request.organization_membership = membership  # type: ignore[attr-defined]
        request.organization = membership.organization if membership is not None else None  # type: ignore[attr-defined]

    def bind_organization(self, organization: Organization | None) -> None:
        """Bind ``organization`` -- possibly ``None`` -- for the rest of the request.

        ``None`` is bound rather than skipped. A caller who resolved to no
        organization must not inherit whatever was bound before them; under
        ``STRICT_ORGANIZATION_FILTER`` a scoped read then raises instead of
        returning someone else's rows.

        Idempotent: the previous binding is released before the new one is
        taken, so a subclass that re-resolves mid-request (after creating the
        caller's first membership, say) neither leaks a context frame nor leaves
        ``dispatch``'s ``finally`` restoring only the second of two.
        """
        self.unbind_organization()
        self._organization_token = set_current_organization(organization)

    def unbind_organization(self) -> None:
        """Release this view's binding, restoring whatever preceded it.

        A no-op when nothing was bound -- the refusals raise before the bind,
        and an unauthenticated request never reaches it.
        """
        token = self._organization_token

        if token is None:
            return

        # Cleared before the reset so that a raising reset -- a token used in a
        # different context than the one that created it -- cannot leave a stale
        # token behind for a second, wrong reset.
        self._organization_token = None
        reset_current_organization(token)

    def perform_authentication(self, request: Request) -> None:
        """Authenticate, then resolve and bind the organization.

        **This is the ordering hook.** ``APIView.initial`` runs, in order:
        content negotiation, versioning, ``perform_authentication``,
        ``check_permissions``, ``check_throttles``. Resolving anywhere after
        that sequence means every permission class runs against whatever
        organization the middleware guessed at, while ``get_queryset`` and the
        object-level checks answer for the resolved one -- a user who
        administers organization A and is a plain member of B passes a
        collection-level administrator gate for a request that then serves B.

        Overriding ``perform_authentication`` rather than reimplementing
        ``initial`` puts the resolution in the one seam between "``request.user``
        is now real" and "``check_permissions`` runs", and leaves every other
        step in its original relative order. Authentication still runs first, so
        an unauthenticated caller is answered 401 by the permission stack rather
        than 400 or 403 by the resolver: the resolver returns ``None`` for an
        anonymous user, and a bad credential raises out of ``super()`` before
        the next line.

        Resolution now also precedes ``check_throttles``. That is the one
        consequence which is not simply "earlier than permissions": a request
        that is ambiguous or names an organization the caller does not belong to
        is refused without spending a throttle bucket. Throttling is not an
        authorization boundary, and refusing a request that cannot even be
        routed is better than counting it.

        The bind lives here rather than inside :meth:`resolve_organization`
        because ``perform_authentication`` is called from exactly one place --
        ``APIView.initial`` -- which is called from exactly one place,
        ``APIView.dispatch``, whose ``finally`` releases the binding.
        """
        super().perform_authentication(request)  # type: ignore[misc]
        self.resolve_organization(request)
        self.bind_organization(request.organization)  # type: ignore[attr-defined]

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        """``super().dispatch``, guaranteeing the binding is released.

        The unbind is here rather than in ``finalize_response`` because
        ``finalize_response`` is not on every path out of ``APIView.dispatch``:
        that method catches into ``handle_exception``, which re-raises anything
        it has no DRF response for -- every non-``APIException``, and the
        ``PermissionDenied`` / ``NotAuthenticated`` that
        ``raise_uncaught_exception`` re-raises. On those paths ``dispatch``
        propagates and never reaches ``finalize_response``.

        A binding that outlived the request would be read by the *next* request
        the worker serves, since a WSGI worker thread reuses its context -- so
        the default manager on every scoped model would answer for the previous
        caller's organization. ``try``/``finally`` around the whole of
        ``dispatch`` is the only placement with no exit path around it.
        """
        try:
            response: HttpResponse = super().dispatch(request, *args, **kwargs)  # type: ignore[misc]
            return response
        finally:
            self.unbind_organization()
