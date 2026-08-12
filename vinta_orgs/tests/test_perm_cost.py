"""Permission checks must not re-query once they have answered.

Each of these has regressed before -- the per-organization caches used to be
replaced wholesale on a miss, and an empty permission set used to read as a
cache miss -- and both cost a query on every check rather than once.
"""

from tests.utils import OrganizationsTestCase
from vinta_orgs.helpers.organizations import create_organization, set_current_organization


class PermissionQueryCountTests(OrganizationsTestCase):
    def test_repeated_checks_are_free(self) -> None:
        self.user.has_perm('vinta_orgs.add_organization')

        with self.assertNumQueries(0):
            self.user.has_perm('vinta_orgs.change_organization')
            self.user.has_perm('vinta_orgs.delete_organization')

    def test_a_permission_the_user_lacks_is_cached_too(self) -> None:
        # An empty set is an answer, not a miss.
        self.user.has_perm('vinta_orgs.nonexistent_permission')

        with self.assertNumQueries(0):
            self.user.has_perm('vinta_orgs.nonexistent_permission')

    def test_switching_back_to_a_known_organization_is_free(self) -> None:
        self.user.has_perm('vinta_orgs.add_organization')

        other = create_organization(name='other', slug='other')
        set_current_organization(other)
        self.user.has_perm('vinta_orgs.add_organization')

        set_current_organization(self.organization)

        with self.assertNumQueries(0):
            self.user.has_perm('vinta_orgs.add_organization')

    def test_a_new_organization_only_costs_its_own_queries(self) -> None:
        self.user.has_perm('vinta_orgs.add_organization')

        other = create_organization(name='other', slug='other')
        set_current_organization(other)

        # One membership lookup and one relationship lookup, each shared
        # between the user and group halves of the check. The user belongs to
        # neither, and both empty results are cached rather than re-queried.
        with self.assertNumQueries(2):
            self.user.has_perm('vinta_orgs.add_organization')

        with self.assertNumQueries(0):
            self.user.has_perm('vinta_orgs.add_organization')
