from django.urls import re_path

from vinta_orgs_custom_data import views

app_name = 'vinta_orgs_custom_data'

urlpatterns = [
    re_path(route=r'^custom-tables/$', view=views.CustomizableModelsList.as_view(), name='custom_tables_list'),
    re_path(
        route=r'^custom-tables/(?P<slug>[\w.@+-]+)/$',
        view=views.CustomTableDetails.as_view(),
        name='custom_tables_details',
    ),
    re_path(
        route=r'^(?P<slug>[\w.@+-]+)/$',
        view=views.OrganizationSpecificTableRowViewset.as_view(
            {
                'get': 'list',
                'post': 'create',
            }
        ),
        name='custom_data_list',
    ),
    re_path(
        route=r'^(?P<slug>[\w.@+-]+)/(?P<pk>[\d]+)/$',
        view=views.OrganizationSpecificTableRowViewset.as_view(
            {
                'get': 'retrieve',
                'put': 'update',
                'patch': 'partial_update',
                'delete': 'destroy',
            }
        ),
        name='custom_data_details',
    ),
]
