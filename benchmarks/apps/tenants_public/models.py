"""django-tenants' public-schema models: the tenant registry itself."""

from django.db import models
from django_tenants.models import DomainMixin, TenantMixin


class Client(TenantMixin):
    name = models.CharField(max_length=255)

    # Creating the row creates the schema and migrates it. The benchmark times
    # that: it is the operational cost schema-per-tenant trades for its
    # isolation.
    auto_create_schema = True


class Domain(DomainMixin):
    pass
