from vinta_orgs_custom_data.forms import OrganizationSpecificModelForm

from .models import Lecture


class LectureForm(OrganizationSpecificModelForm):
    class Meta:
        model = Lecture
        fields = ['id', 'subject', 'speaker', 'description']
