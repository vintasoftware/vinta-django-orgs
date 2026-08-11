from django.urls import re_path

from . import views

app_name = 'organizations'

urlpatterns = [
    re_path(route=r'^organization/$', view=views.OrganizationListView.as_view(), name='organization_list'),
    re_path(
        route=r'^organization/details/$', view=views.OrganizationDetailsView.as_view(), name='organization_details'
    ),
    re_path(
        route=r'^organization-site/$', view=views.OrganizationSiteListView.as_view(), name='organization_site_list'
    ),
    re_path(
        route=r'^organization-site/(?P<pk>[\d]+)/$',
        view=views.OrganizationSiteDetailsView.as_view(),
        name='organization_site_details',
    ),
]
