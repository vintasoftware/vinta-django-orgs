from django.urls import re_path

from . import views

app_name = 'lectures'

urlpatterns = [
    re_path(
        route=r'^$',
        view=views.LectureViewSet.as_view(
            {
                'get': 'list',
                'post': 'create',
            }
        ),
        name='list',
    ),
    re_path(
        route=r'^(?P<pk>\d+)/$',
        view=views.LectureViewSet.as_view(
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
