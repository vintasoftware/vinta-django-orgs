from unittest import mock

from django.test import TestCase, override_settings

from organizations import settings as organization_settings
from organizations.settings import get_setting


class GetSettingTests(TestCase):
    def test_returns_the_default_when_the_project_configures_nothing(self) -> None:
        self.assertEqual(get_setting('DEFAULT_SITE_DOMAIN'), 'localhost')
        self.assertEqual(get_setting('DEFAULT_ORGANIZATION_SLUG'), 'default')
        self.assertFalse(get_setting('STRICT_ORGANIZATION_FILTER'))

    def test_unknown_setting_returns_none(self) -> None:
        self.assertIsNone(get_setting('NOT_A_SETTING'))

    def test_resolves_the_configuration_only_once(self) -> None:
        get_setting('DEFAULT_SITE_DOMAIN')

        with mock.patch.object(organization_settings, '_build_settings') as build_settings:
            get_setting('DEFAULT_SITE_DOMAIN')
            get_setting('ORGANIZATION_RETRIEVERS')

        build_settings.assert_not_called()

    def test_override_settings_invalidates_the_cache(self) -> None:
        self.assertEqual(get_setting('DEFAULT_SITE_DOMAIN'), 'localhost')

        with override_settings(SHARED_SCHEMA_ORGANIZATIONS={'DEFAULT_SITE_DOMAIN': 'example.com'}):
            self.assertEqual(get_setting('DEFAULT_SITE_DOMAIN'), 'example.com')

        self.assertEqual(get_setting('DEFAULT_SITE_DOMAIN'), 'localhost')

    @override_settings(
        SHARED_SCHEMA_ORGANIZATIONS={
            'SERIALIZERS': {'ORGANIZATION_MEMBERSHIP_SERIALIZER': 'exampleproject.MembershipSerializer'}
        }
    )
    def test_membership_serializer_reads_its_own_key(self) -> None:
        self.assertEqual(get_setting('ORGANIZATION_MEMBERSHIP_SERIALIZER'), 'exampleproject.MembershipSerializer')

    def test_membership_serializer_is_none_when_unconfigured(self) -> None:
        self.assertIsNone(get_setting('ORGANIZATION_MEMBERSHIP_SERIALIZER'))
