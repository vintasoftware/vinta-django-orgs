from django.test import TestCase

from vinta_orgs.utils import import_from_string


class ImportFromStringTests(TestCase):
    def test_class_is_really_imported(self) -> None:
        OrganizationSerializer = import_from_string('vinta_orgs.serializers.OrganizationSerializer')

        self.assertEqual(OrganizationSerializer.__name__, 'OrganizationSerializer')
