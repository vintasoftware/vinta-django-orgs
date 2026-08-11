from django.urls import include, re_path

urlpatterns = [
    re_path(r'^lectures/', include('exampleproject.lectures.urls', namespace='lectures')),
    re_path(r'^', include('organizations.urls', namespace='organizations')),
    re_path(r'^', include('organizations_custom_data.urls', namespace='organizations_custom_data')),
]
