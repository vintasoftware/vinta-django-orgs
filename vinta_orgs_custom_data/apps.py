from django.apps import AppConfig
from django.db.models.signals import m2m_changed, post_save


class OrganizationsCustomDataConfig(AppConfig):
    name = 'vinta_orgs_custom_data'
    # Keeps the primary keys already created by 0001_initial, regardless of the
    # DEFAULT_AUTO_FIELD chosen by the project using this app.
    default_auto_field = 'django.db.models.AutoField'

    def ready(self) -> None:
        """Connect the membership receivers to whichever membership model is configured.

        Connected here rather than with ``@receiver(..., sender=OrganizationMembership)``
        at module level, because the membership model is swappable: a project
        that set ``ORGANIZATION_MEMBERSHIP_MODEL`` writes rows of *its* model, and
        a receiver bound to the class this library ships would never fire. The
        ``m2m_changed`` one needs the through model, which cannot be named as a
        string at all, so both are resolved here where the app registry is
        populated.
        """
        from vinta_orgs.conf import get_organization_membership_model
        from vinta_orgs_custom_data.models import (
            add_group_organization_specific_tables_relationship,
            create_organization_specific_tables_relationship,
        )

        membership_model = get_organization_membership_model()

        post_save.connect(create_organization_specific_tables_relationship, sender=membership_model)
        m2m_changed.connect(
            add_group_organization_specific_tables_relationship, sender=membership_model.groups.through
        )
