from django.urls import re_path

from . import views

app_name = 'articles'

urlpatterns = [
    re_path(
        route=r'^$',
        view=views.ArticleViewSet.as_view(
            {
                'get': 'list',
                'post': 'create',
            }
        ),
        name='list',
    ),
    re_path(
        route=r'^(?P<pk>\d+)/$',
        view=views.ArticleViewSet.as_view(
            {
                'get': 'retrieve',
                'put': 'update',
                'patch': 'partial_update',
                'delete': 'destroy',
            }
        ),
        name='details',
    ),
    re_path(
        route=r'^tags/$',
        view=views.TagViewSet.as_view(
            {
                'get': 'list',
                'post': 'create',
            }
        ),
        name='list',
    ),
    re_path(
        route=r'^tags/(?P<pk>\d+)/$',
        view=views.TagViewSet.as_view(
            {
                'get': 'retrieve',
                'put': 'update',
                'patch': 'partial_update',
                'delete': 'destroy',
            }
        ),
        name='details',
    ),
]
