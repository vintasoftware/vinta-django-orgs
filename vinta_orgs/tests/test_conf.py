"""The swappable-model plumbing.

Every assertion here holds under both settings modules the suite runs against:
``tests.settings``, which leaves ``ORGANIZATION_MODEL`` and
``ORGANIZATION_MEMBERSHIP_MODEL`` at their defaults, and
``tests.settings_swapped``, which points them at ``exampleproject.customorgs``.
That is the point -- they describe the contract rather than one configuration,
and the swapped run is what proves the contract is real.
"""

from django.conf import settings
from django.contrib import admin
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Model
from django.test import TestCase, override_settings

from vinta_orgs.conf import (
    DEFAULT_ORGANIZATION_MEMBERSHIP_MODEL,
    DEFAULT_ORGANIZATION_MODEL,
    apply_setting_defaults,
    get_organization_membership_model,
    get_organization_model,
    organization_membership_model_string,
    organization_model_string,
)
from vinta_orgs.helpers.organizations import organization_context
from vinta_orgs.models import (
    AbstractOrganization,
    AbstractOrganizationMembership,
    Organization,
    OrganizationMembership,
    OrganizationSite,
)
from vinta_orgs.settings import get_setting


class ModelResolutionTests(TestCase):
    def test_the_settings_always_exist(self) -> None:
        # Defaulted onto the settings object by ``OrganizationsConfig``, because
        # the migrations Django generates read them directly.
        self.assertTrue(hasattr(settings, 'ORGANIZATION_MODEL'))
        self.assertTrue(hasattr(settings, 'ORGANIZATION_MEMBERSHIP_MODEL'))

    def test_resolves_the_configured_models(self) -> None:
        self.assertEqual(get_organization_model()._meta.label, organization_model_string())
        self.assertEqual(get_organization_membership_model()._meta.label, organization_membership_model_string())

    def test_the_configured_models_extend_the_abstract_bases(self) -> None:
        # What the library actually depends on: whatever is configured has to be
        # one of these, so ``name``, ``slug`` and the membership's relations are
        # guaranteed to be there.
        self.assertTrue(issubclass(get_organization_model(), AbstractOrganization))
        self.assertTrue(issubclass(get_organization_membership_model(), AbstractOrganizationMembership))

    def test_applying_defaults_does_not_overwrite_a_configured_value(self) -> None:
        with override_settings(ORGANIZATION_MODEL='somewhere.Else'):
            apply_setting_defaults()

            self.assertEqual(organization_model_string(), 'somewhere.Else')

    def test_a_malformed_setting_is_reported(self) -> None:
        with override_settings(ORGANIZATION_MODEL='NotAnAppLabel'), self.assertRaises(ImproperlyConfigured):
            get_organization_model()

    def test_an_uninstalled_model_is_reported(self) -> None:
        with override_settings(ORGANIZATION_MODEL='nosuchapp.Organization'), self.assertRaises(ImproperlyConfigured):
            get_organization_model()


class SwappableWiringTests(TestCase):
    """The concrete models shipped here declare themselves swappable."""

    def test_the_shipped_models_name_their_settings(self) -> None:
        self.assertEqual(Organization._meta.swappable, 'ORGANIZATION_MODEL')
        self.assertEqual(OrganizationMembership._meta.swappable, 'ORGANIZATION_MEMBERSHIP_MODEL')

    def test_swapped_is_set_only_when_another_model_is_configured(self) -> None:
        # ``Options.swapped`` is what stops Django creating a table for a model
        # that has been replaced, and what the admin refuses to register.
        swapped_out = organization_model_string().lower() != DEFAULT_ORGANIZATION_MODEL.lower()

        self.assertEqual(bool(Organization._meta.swapped), swapped_out)
        self.assertEqual(
            bool(OrganizationMembership._meta.swapped),
            organization_membership_model_string().lower() != DEFAULT_ORGANIZATION_MEMBERSHIP_MODEL.lower(),
        )


class RelationTargetTests(TestCase):
    """Every relation to an organization follows the setting."""

    def test_scoped_models_point_at_the_configured_organization(self) -> None:
        from exampleproject.articles.models import Article, Tag

        organization_model = get_organization_model()

        targets: list[tuple[type[Model], str]] = [
            (Article, 'organization'),
            (OrganizationSite, 'organization'),
            (get_organization_membership_model(), 'organization'),
            (Tag, 'organizations'),
        ]

        for model, field_name in targets:
            with self.subTest(model=model.__name__):
                self.assertIs(model._meta.get_field(field_name).related_model, organization_model)

    def test_the_reverse_accessors_still_resolve(self) -> None:
        organization = get_organization_model()._default_manager.create(name='test', slug='test')

        # ``organization_sites`` is a scoped model's reverse accessor, so it
        # narrows to the *selected* organization on top of the relation --
        # under ``STRICT_ORGANIZATION_FILTER`` reading it unbound raises rather
        # than quietly answering nothing. ``memberships`` does not, which is
        # the whole reason its manager is unscoped.
        with organization_context(organization):
            # Named on the relations in ``models.py``; a project that swaps the
            # organization inherits them, which is what the library reads.
            self.assertEqual(organization.memberships.count(), 0)
            self.assertEqual(organization.organization_sites.count(), 0)


class OwnerPermissionsTests(TestCase):
    """The default owner permissions are derived, not spelled out."""

    def test_permissions_name_the_configured_apps(self) -> None:
        permissions = get_setting('DEFAULT_ORGANIZATION_OWNER_PERMISSIONS')
        organization_model = get_organization_model()
        expected = '%s.change_%s' % (organization_model._meta.app_label, organization_model._meta.model_name)

        self.assertIn(expected, permissions)

    def test_every_permission_actually_exists(self) -> None:
        # The failure this guards is quiet: a permission that Django never
        # created is skipped when the owner group is built, so the group comes
        # out empty and every ``DjangoModelPermissions`` check 403s.
        from django.contrib.auth.models import Permission

        for label in get_setting('DEFAULT_ORGANIZATION_OWNER_PERMISSIONS'):
            app_label, codename = label.split('.')
            with self.subTest(permission=label):
                self.assertTrue(
                    Permission.objects.filter(content_type__app_label=app_label, codename=codename).exists()
                )


class AdminRegistrationTests(TestCase):
    def test_the_configured_models_are_registered(self) -> None:
        self.assertIn(get_organization_model(), admin.site._registry)
        self.assertIn(get_organization_membership_model(), admin.site._registry)
