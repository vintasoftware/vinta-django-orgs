"""Sphinx configuration for the Vinta Django Orgs documentation."""

import os
import sys

# The docs live in ``docs/``; the package they document is one level up.
sys.path.insert(0, os.path.abspath('..'))

# ``autodoc`` imports the modules it documents, and importing anything that
# touches models requires a configured Django. The test settings already wire up
# the app and its dependencies, so they double as the docs settings.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tests.settings')

import django  # noqa: E402

django.setup()

import vinta_orgs  # noqa: E402

# -- Project information -------------------------------------------------------

project = 'Vinta Django Orgs'
copyright = '2026, Vinta Software'
author = 'Vinta Software'

version = vinta_orgs.__version__
release = vinta_orgs.__version__

# -- General configuration -----------------------------------------------------

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.intersphinx',
    'sphinx.ext.viewcode',
    'sphinx_copybutton',
]

templates_path = ['_templates']
exclude_patterns = ['_build', 'plans', 'Thumbs.db', '.DS_Store']

# Bare ``text`` in reST renders as code, which is what most inline references in
# these pages mean.
default_role = 'literal'

# Links to the Python/Django/DRF docs resolve to those projects' own pages
# instead of rendering as plain, unlinked type names.
intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
    'django': (
        'https://docs.djangoproject.com/en/stable/',
        'https://docs.djangoproject.com/en/stable/_objects/',
    ),
}

autodoc_member_order = 'bysource'
autodoc_typehints = 'description'
# Overridden methods (``as_sql``, DRF's ``create``/``update``) otherwise inherit
# their base class's docstring, which describes the base behaviour and is not
# always valid reST.
autodoc_inherit_docstrings = False

# -- Options for HTML output ---------------------------------------------------

html_theme = 'furo'
html_title = f'Vinta Django Orgs {version}'
html_static_path = ['_static']
html_css_files = ['custom.css']

html_theme_options = {
    # Furo derives the whole accent scheme from these two, one per color mode.
    'light_css_variables': {
        'color-brand-primary': '#0b7285',
        'color-brand-content': '#0b7285',
    },
    'dark_css_variables': {
        'color-brand-primary': '#63d3dd',
        'color-brand-content': '#63d3dd',
    },
    'source_repository': 'https://github.com/vintasoftware/vinta-django-orgs/',
    'source_branch': 'main',
    'source_directory': 'docs/',
    'footer_icons': [
        {
            'name': 'GitHub',
            'url': 'https://github.com/vintasoftware/vinta-django-orgs',
            'class': 'fa-brands fa-github',
            'html': (
                '<svg stroke="currentColor" fill="currentColor" stroke-width="0" viewBox="0 0 16 16">'
                '<path fill-rule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59'
                '.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13'
                '-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07'
                '-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82'
                '.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82'
                '1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46'
                '.55.38A8.012 8.012 0 0 0 16 8c0-4.42-3.58-8-8-8z"></path></svg>'
            ),
        },
    ],
}

# -- Options for other builders ------------------------------------------------

htmlhelp_basename = 'vinta-django-orgs-doc'

latex_documents = [
    ('index', 'vinta-django-orgs.tex', 'Vinta Django Orgs Documentation', author, 'manual'),
]

man_pages = [
    ('index', 'vinta-django-orgs', 'Vinta Django Orgs Documentation', [author], 1),
]

texinfo_documents = [
    (
        'index',
        'vinta-django-orgs',
        'Vinta Django Orgs Documentation',
        author,
        'vinta-django-orgs',
        'Shared schema multi-organization applications for Django.',
        'Miscellaneous',
    ),
]
