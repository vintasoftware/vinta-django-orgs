from typing import Any

from django import forms
from django.contrib import admin
from django.contrib.sites.models import Site
from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

from organizations.models import Organization, OrganizationMembership, OrganizationSite


class OrganizationSiteForm(forms.ModelForm):
    site = forms.CharField(max_length=255)

    class Meta:
        model = OrganizationSite
        fields = ['site', 'organization']

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        if instance:
            self.initial['site'] = instance.site.domain

    def clean_site(self) -> Site:
        site = self.cleaned_data['site']
        instance = self.instance
        new_site_instance, created = Site.objects.get_or_create(domain=site, defaults={'name': self.data['name']})
        try:
            old_site_instance = instance.site
        except Site.DoesNotExist:
            old_site_instance = None

        if not created and old_site_instance and old_site_instance != new_site_instance:
            raise ValidationError(_('A site with this domain already asigned to an organization'))

        return new_site_instance

    def save(self, *args: Any, **kwargs: Any) -> OrganizationSite:
        instance = self.instance
        delete_old_site = False
        if instance:
            old_instance = OrganizationSite.objects.filter(id=instance.id).first()
            if old_instance and old_instance.site != self.cleaned_data['site']:
                delete_old_site = True
                old_site = old_instance.site

        instance = super().save(*args, **kwargs)

        if delete_old_site:
            old_site.delete()

        return instance


class OrganizationSiteInLine(admin.StackedInline):
    model = OrganizationSite
    form = OrganizationSiteForm
    extra = 0
    min_num = 1

    def get_queryset(self, request: HttpRequest) -> QuerySet[OrganizationSite]:
        # The form's ``__init__`` reads ``instance.site.domain`` to fill in its
        # initial value, and ``__str__`` reads the site and the organization, so
        # each row costs its own queries without this.
        return super().get_queryset(request).select_related('site', 'organization')


class OrganizationAdmin(admin.ModelAdmin):
    model = Organization
    inlines = [OrganizationSiteInLine]
    prepopulated_fields = {'slug': ('name',)}


class OrganizationMembershipAdmin(admin.ModelAdmin):
    model = OrganizationMembership

    def get_queryset(self, request: HttpRequest) -> QuerySet[OrganizationMembership]:
        # ``OrganizationMembership.__str__`` reads the user, the organization
        # and every group, which the changelist renders once per row -- three
        # queries per row, so a page of a hundred cost three hundred.
        return super().get_queryset(request).select_related('user', 'organization').prefetch_related('groups')


admin.site.register(Organization, OrganizationAdmin)
admin.site.register(OrganizationMembership, OrganizationMembershipAdmin)
