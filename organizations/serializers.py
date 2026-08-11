from typing import Any

from django.contrib.sites.models import Site
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from organizations.helpers.organizations import create_organization, get_current_organization, update_organization
from organizations.models import Organization, OrganizationSite


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ['name', 'slug']

    def create(self, validated_data: dict[str, Any]) -> Organization:
        return create_organization(user=self.context['request'].user, **validated_data)

    def update(self, instance: Organization, validated_data: dict[str, Any]) -> Organization:
        return update_organization(instance, **validated_data)


class OrganizationSiteSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    domain = serializers.CharField(required=True)

    # Widened deliberately: DRF's contract is instance -> dict, and this
    # renders ``None`` for a missing organization site rather than an empty
    # object.
    def to_representation(  # type: ignore[override]
        self, instance: OrganizationSite | None
    ) -> dict[str, Any] | None:
        if instance:
            return {'id': instance.id, 'domain': instance.site.domain}
        return None

    def validate_domain(self, domain: str) -> str:
        if Site.objects.filter(domain=domain).exists():
            raise ValidationError(_('This domain is already being used by another organization'))

        return domain

    def create(self, validated_data: dict[str, Any]) -> OrganizationSite:
        organization = get_current_organization()
        domain = validated_data['domain']

        with transaction.atomic():
            site = Site.objects.create(name=domain, domain=domain)
            return OrganizationSite.objects.create(organization=organization, site=site)
