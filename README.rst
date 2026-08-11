==================================
Django Shared Schema Organizations
==================================

.. image:: https://badge.fury.io/py/django-shared-schema-organizations.svg
    :target: https://badge.fury.io/py/django-shared-schema-organizations

.. image:: https://github.com/hugobessa/django-shared-schema-organizations/actions/workflows/ci.yml/badge.svg
    :target: https://github.com/hugobessa/django-shared-schema-organizations/actions/workflows/ci.yml

.. image:: https://codecov.io/gh/hugobessa/django-shared-schema-organizations/branch/master/graph/badge.svg
    :target: https://codecov.io/gh/hugobessa/django-shared-schema-organizations

A lib to help in the creation applications with shared schema without suffering

Documentation
-------------

The full documentation is at [ReadTheDocs](https://django-shared-schema-organizations.readthedocs.io).

Quickstart
----------

Install Django Shared Schema Organizations::

    pip install django-shared-schema-organizations

Add it to your `INSTALLED_APPS`:

.. code-block:: python

    INSTALLED_APPS = (
        ...
        'organizations.apps.OrganizationsConfig',
        ...
    )

Add Django Shared Schema Organizations's URL patterns:

.. code-block:: python

    from django.urls import include, path


    urlpatterns = [
        ...
        path('', include('organizations.urls')),
        ...
    ]


Add OrganizationMiddleware to your `MIDDLEWARES`:

.. code-block:: python

    MIDDLEWARES = [
        # ...
        'organizations.middleware.OrganizationMiddleware',
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

Credits
-------

Tools used in rendering this package:

*  Cookiecutter_
*  `cookiecutter-djangopackage`_

.. _Cookiecutter: https://github.com/audreyr/cookiecutter
.. _`cookiecutter-djangopackage`: https://github.com/pydanny/cookiecutter-djangopackage
