=================
Vinta Django Orgs
=================

.. image:: https://badge.fury.io/py/vinta-django-orgs.svg
    :target: https://badge.fury.io/py/vinta-django-orgs

.. image:: https://github.com/hugobessa/django-shared-schema-organizations/actions/workflows/ci.yml/badge.svg
    :target: https://github.com/vintasoftware/vinta-django-orgs/actions/workflows/ci.yml

.. image:: https://codecov.io/gh/hugobessa/django-shared-schema-organizations/branch/master/graph/badge.svg
    :target: https://codecov.io/gh/vintasoftware/vinta-django-orgs

A lib to help in the creation applications with shared schema without suffering

Documentation
-------------

The full documentation is at [ReadTheDocs](https://vinta-django-orgs.readthedocs.io).

Quickstart
----------

Install Django Shared Schema Organizations::

    pip install vinta-django-orgs

Add it to your `INSTALLED_APPS`:

.. code-block:: python

    INSTALLED_APPS = (
        ...
        'vinta_orgs.apps.OrganizationsConfig',
        ...
    )

Add Django Shared Schema Organizations's URL patterns:

.. code-block:: python

    from django.urls import include, path


    urlpatterns = [
        ...
        path('', include('vinta_orgs.urls')),
        ...
    ]


Add OrganizationMiddleware to your `MIDDLEWARES`:

.. code-block:: python

    MIDDLEWARES = [
        # ...
        'vinta_orgs.middleware.OrganizationMiddleware',
        # ...
    ]


Features
--------

* **Organizations synced with django requests:** The active organization can be extracted from the domain of the request and from a specific http header attribute.
* **Easy data isolation between organizations:** You retrieve and create data the same way you do without organizations. The active organization can be retrieved from the request, and can also be forcedly set.
* **Partially shared data:** If there is data that can be accessed from more then one organization in your applidation, you don't need to duplicate it.


Running Tests
-------------

Does the code actually work?

::

    $ uv sync
    $ uv run tox
