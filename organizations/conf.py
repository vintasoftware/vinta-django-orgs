"""Which organization and membership models this project actually uses.

``Organization`` and ``OrganizationMembership`` are swappable, the way
``auth.User`` is: a project that needs a field on either one declares its own
model inheriting the matching abstract base and points a setting at it, instead
of hanging a one-to-one companion off the concrete model shipped here.

    # settings.py
    ORGANIZATION_MODEL = 'tenancy.Organization'
    ORGANIZATION_MEMBERSHIP_MODEL = 'tenancy.OrganizationMembership'

Django resolves ``Meta.swappable`` through a *top-level* setting -- it does a
plain ``getattr(settings, 'ORGANIZATION_MODEL')`` -- so these two cannot live
inside the ``SHARED_SCHEMA_ORGANIZATIONS`` dictionary with everything else. The
names mirror ``AUTH_USER_MODEL`` for the same reason.

Both settings default to the concrete models in this app, so a project that
does not care never has to mention them. That default is *written back onto the
settings object* by :func:`apply_setting_defaults`, called from
``OrganizationsConfig`` before any model is imported. Django's own swappable
machinery reads the setting directly in the migrations it generates
(``migrations.swappable_dependency(settings.ORGANIZATION_MODEL)``), and would
raise ``AttributeError`` on a project that never set it -- so the attribute has
to exist, not merely have a default this module knows about.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.apps import apps as django_apps
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

if TYPE_CHECKING:
    from organizations.models import Organization, OrganizationMembership

#: Setting names, so nothing has to spell them as bare strings.
ORGANIZATION_MODEL_SETTING = 'ORGANIZATION_MODEL'
ORGANIZATION_MEMBERSHIP_MODEL_SETTING = 'ORGANIZATION_MEMBERSHIP_MODEL'

DEFAULT_ORGANIZATION_MODEL = 'organizations.Organization'
DEFAULT_ORGANIZATION_MEMBERSHIP_MODEL = 'organizations.OrganizationMembership'

_DEFAULTS = {
    ORGANIZATION_MODEL_SETTING: DEFAULT_ORGANIZATION_MODEL,
    ORGANIZATION_MEMBERSHIP_MODEL_SETTING: DEFAULT_ORGANIZATION_MEMBERSHIP_MODEL,
}


def apply_setting_defaults() -> None:
    """Give the swappable settings their defaults if the project did not.

    Called from ``OrganizationsConfig.__init__``, which runs while Django is
    building the app registry and before it imports any ``models`` module -- the
    two model classes read these settings at class-definition time, and so does
    every migration that points a foreign key at them.

    Idempotent, and never overwrites a value the project set.
    """
    for name, default in _DEFAULTS.items():
        if not hasattr(settings, name):
            setattr(settings, name, default)


def organization_model_string() -> str:
    """The ``'app_label.ModelName'`` of the organization model in use."""
    return getattr(settings, ORGANIZATION_MODEL_SETTING, DEFAULT_ORGANIZATION_MODEL)


def organization_membership_model_string() -> str:
    """The ``'app_label.ModelName'`` of the membership model in use."""
    return getattr(settings, ORGANIZATION_MEMBERSHIP_MODEL_SETTING, DEFAULT_ORGANIZATION_MEMBERSHIP_MODEL)


def _get_model(setting_name: str, model_string: str) -> Any:
    try:
        return django_apps.get_model(model_string, require_ready=False)
    except ValueError as exc:
        raise ImproperlyConfigured("%s must be of the form 'app_label.ModelName'" % setting_name) from exc
    except LookupError as exc:
        raise ImproperlyConfigured(
            "%s refers to model '%s', which has not been installed" % (setting_name, model_string)
        ) from exc


def get_organization_model() -> type[Organization]:
    """Return the organization model this project is configured to use.

    The counterpart of ``django.contrib.auth.get_user_model()``, and it has the
    same rule: call it, do not import ``Organization`` directly, or a project
    that swapped the model gets the wrong class.
    """
    # Annotated as the *concrete* model rather than ``AbstractOrganization``,
    # which is a deliberate approximation: reverse accessors
    # (``organization.memberships``, ``organization.organization_sites``) are
    # generated only for concrete models, so the abstract base would type-check
    # away half of what this library does with the object it returns.
    #
    # It is also what actually holds for whoever is running the type checker.
    # mypy analyses one settings module at a time, and under that settings module
    # this returns exactly one class. django-stubs makes the same approximation
    # for ``get_user_model()``. A project that swaps the model reads its own
    # class directly and gets its own fields.
    organization_model: type[Organization] = _get_model(ORGANIZATION_MODEL_SETTING, organization_model_string())
    return organization_model


def get_organization_membership_model() -> type[OrganizationMembership]:
    """Return the membership model this project is configured to use."""
    membership_model: type[OrganizationMembership] = _get_model(
        ORGANIZATION_MEMBERSHIP_MODEL_SETTING, organization_membership_model_string()
    )
    return membership_model
