from django.contrib import admin

from vinta_orgs_custom_data.forms import OrganizationSpecificModelForm
from vinta_orgs_custom_data.models import (
    OrganizationSpecificFieldDefinition,
    OrganizationSpecificFieldsValidator,
    OrganizationSpecificTable,
    OrganizationSpecificTableRow,
)


class OrganizationSpecificModelAdmin(admin.ModelAdmin):
    form = OrganizationSpecificModelForm


admin.site.register(OrganizationSpecificTable)
admin.site.register(OrganizationSpecificFieldDefinition)
admin.site.register(OrganizationSpecificTableRow)
admin.site.register(OrganizationSpecificFieldsValidator)
