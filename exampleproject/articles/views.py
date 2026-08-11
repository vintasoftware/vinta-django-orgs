from django.db.models import QuerySet
from rest_framework import permissions, viewsets

from .models import Article, Tag
from .serializers import ArticleSerializer, TagSerializer


class ArticleViewSet(viewsets.ModelViewSet):
    serializer_class = ArticleSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self) -> QuerySet[Article]:
        return Article.objects.all()


class TagViewSet(viewsets.ModelViewSet):
    serializer_class = TagSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self) -> QuerySet[Tag]:
        return Tag.objects.all()
