============
Contributing
============

Contributions are welcome, and they are greatly appreciated! Every
little bit helps, and credit will always be given.

You can contribute in many ways:

Types of Contributions
----------------------

Report Bugs
~~~~~~~~~~~

Report bugs at https://github.com/hugobessa/django-shared-schema-organizations/issues.

If you are reporting a bug, please include:

* Your operating system name and version.
* Any details about your local setup that might be helpful in troubleshooting.
* Detailed steps to reproduce the bug.

Fix Bugs
~~~~~~~~

Look through the GitHub issues for bugs. Anything tagged with "bug"
is open to whoever wants to implement it.

Implement Features
~~~~~~~~~~~~~~~~~~

Look through the GitHub issues for features. Anything tagged with "feature"
is open to whoever wants to implement it.

Write Documentation
~~~~~~~~~~~~~~~~~~~

Django Shared Schema Organizations could always use more documentation, whether as part of the
official Django Shared Schema Organizations docs, in docstrings, or even on the web in blog posts,
articles, and such.

Submit Feedback
~~~~~~~~~~~~~~~

The best way to send feedback is to file an issue at https://github.com/hugobessa/django-shared-schema-organizations/issues.

If you are proposing a feature:

* Explain in detail how it would work.
* Keep the scope as narrow as possible, to make it easier to implement.
* Remember that this is a volunteer-driven project, and that contributions
  are welcome :)

Get Started!
------------

Ready to contribute? Here's how to set up `django-shared-schema-organizations` for local development.

1. Fork the `django-shared-schema-organizations` repo on GitHub.
2. Clone your fork locally::

    $ git clone git@github.com:your_name_here/django-shared-schema-organizations.git

3. Install your local copy. Dependencies are managed with `uv <https://docs.astral.sh/uv/>`_,
   which creates the virtualenv and installs the project in editable mode for you::

    $ cd django-shared-schema-organizations/
    $ uv sync
    $ make hooks

   ``make hooks`` installs the pre-commit hooks, so every commit is linted and
   type-checked before it lands.

4. Create a branch for local development::

    $ git checkout -b name-of-your-bugfix-or-feature

   Now you can make your changes locally.

5. When you're done making changes, check that your changes pass ruff, mypy and
   the tests, including testing every supported Python and Django version with
   tox::

        $ make lint
        $ make typecheck
        $ make test
        $ make test-all

   `ruff <https://docs.astral.sh/ruff/>`_ is both the linter and the formatter.
   ``make lint`` checks both; ``make format`` applies the automatic fixes and
   reformats. ``make pre-commit`` runs all of that together with the file-hygiene
   hooks over the whole tree, which is what CI checks.

   ``make typecheck`` runs `mypy <https://mypy.readthedocs.io/>`_ with the
   `django-stubs <https://github.com/typeddjango/django-stubs>`_ and
   `djangorestframework-stubs
   <https://github.com/typeddjango/djangorestframework-stubs>`_ plugins, which
   is what lets it follow managers, reverse accessors and serializer fields.
   The plugin reads ``tests.settings`` (see ``[tool.django-stubs]`` in
   ``pyproject.toml``), so it needs the project installed rather than just the
   sources. Both packages ship a ``py.typed`` marker, so the annotations are
   part of the public API: a signature change is a breaking change for anyone
   type-checking against this library. The whole tree is checked under
   ``disallow_untyped_defs``, tests included.

   Every tool comes from the ``dev`` dependency group, so ``uv sync`` is all the
   setup you need. If you add or change a dependency, edit ``pyproject.toml`` and
   run ``uv lock`` to refresh ``uv.lock`` -- the ``uv-lock`` hook fails the commit
   if you forget.

6. Commit your changes and push your branch to GitHub::

    $ git add .
    $ git commit -m "Your detailed description of your changes."
    $ git push origin name-of-your-bugfix-or-feature

7. Submit a pull request through the GitHub website.

Pull Request Guidelines
-----------------------

Before you submit a pull request, check that it meets these guidelines:

1. The pull request should include tests.
2. If the pull request adds functionality, the docs should be updated. Put
   your new functionality into a function with a docstring, and add the
   feature to the list in README.rst.
3. The pull request should work for every supported Python (3.11 to 3.15) and
   Django (5.2 to 6.2) version. Check the GitHub Actions run on your pull request
   and make sure that the whole matrix passes.

Tips
----

To run a subset of tests::

    $ uv run python runtests.py vinta_orgs.tests.test_models

To run the example project against your working tree::

    $ uv run python exampleproject/manage.py migrate
    $ uv run python exampleproject/manage.py runserver
