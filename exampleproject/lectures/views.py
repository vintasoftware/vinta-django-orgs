from django.db.models import QuerySet
from rest_framework import permissions, viewsets

from .models import Lecture
from .serializers import LectureSerializer


class LectureViewSet(viewsets.ModelViewSet):
    serializer_class = LectureSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self) -> QuerySet[Lecture]:
        return Lecture.objects.all()
