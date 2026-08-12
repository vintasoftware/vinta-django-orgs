============
Installation
============

At the command line::

    $ pip install vinta-django-orgs

Or, if your project is managed with `uv <https://docs.astral.sh/uv/>`_::

    $ uv add vinta-django-orgs


To use Vinta Django Orgs in a project, add it to your ``INSTALLED_APPS``:

.. code-block:: python

    INSTALLED_APPS = (
        ...
        'vinta_orgs.apps.OrganizationsConfig',
        ...
    )


You also have to add OrganizationMiddleware to django  `MIDDLEWARES`:

.. code-block:: python

    MIDDLEWARES = [
        # ...
        'vinta_orgs.middleware.OrganizationMiddleware',
        # ...
    ]
