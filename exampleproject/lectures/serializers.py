from rest_framework import serializers

from organizations_custom_data.serializers import OrganizationSpecificModelSerializer

from .models import Lecture


class LectureSerializer(OrganizationSpecificModelSerializer):
    speaker_name = serializers.SerializerMethodField()

    class Meta:
        model = Lecture
        fields = ['id', 'subject', 'speaker', 'speaker_name', 'description']

    def get_speaker_name(self, obj: Lecture) -> str:
        return obj.speaker.first_name + ' ' + obj.speaker.last_name
