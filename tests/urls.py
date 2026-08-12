from django.urls import include, re_path

urlpatterns = [
    re_path(r'^lectures/', include('exampleproject.lectures.urls', namespace='lectures')),
    re_path(r'^', include('vinta_orgs.urls', namespace='vinta_orgs')),
    re_path(r'^', include('vinta_orgs_custom_data.urls', namespace='vinta_orgs_custom_data')),
]
