from django.contrib import admin

from vinta_orgs_custom_data.admin import OrganizationSpecificModelAdmin

from .models import Lecture


class LectureAdmin(OrganizationSpecificModelAdmin):
    pass


admin.site.register(Lecture, LectureAdmin)
