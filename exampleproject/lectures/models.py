from django.conf import settings
from django.db import models

from organizations_custom_data.mixins import OrganizationSpecificFieldsModelMixin


class Lecture(OrganizationSpecificFieldsModelMixin):
    subject = models.CharField(max_length=100)
    description = models.TextField()
    speaker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    def __str__(self) -> str:
        return '%s - %s' % (self.subject, self.speaker)
