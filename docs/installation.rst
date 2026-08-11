============
Installation
============

At the command line::

    $ pip install django-shared-schema-organizations

Or, if your project is managed with `uv <https://docs.astral.sh/uv/>`_::

    $ uv add django-shared-schema-organizations


To use Django Shared Schema Organizations in a project, add it to your `INSTALLED_APPS`:

.. code-block:: python

    INSTALLED_APPS = (
        ...
        'organizations.apps.OrganizationsConfig',
        ...
    )


You also have to add OrganizationMiddleware to django  `MIDDLEWARES`:

.. code-block:: python

    MIDDLEWARES = [
        # ...
        'organizations.middleware.OrganizationMiddleware',
        # ...
    ]
