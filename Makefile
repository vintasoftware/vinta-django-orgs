.PHONY: clean clean-pyc clean-build docs docs-serve help install lock lint typecheck format hooks pre-commit test test-all coverage release dist bench bench-db bench-db-stop
.DEFAULT_GOAL := help
define BROWSER_PYSCRIPT
import os, webbrowser, sys
from urllib.request import pathname2url

webbrowser.open("file://" + pathname2url(os.path.abspath(sys.argv[1])))
endef
export BROWSER_PYSCRIPT
BROWSER := uv run python -c "$$BROWSER_PYSCRIPT"

help:
	@perl -nle'print $& if m{^[a-zA-Z_-]+:.*?## .*$$}' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-25s\033[0m %s\n", $$1, $$2}'

clean: clean-build clean-pyc

clean-build: ## remove build artifacts
	rm -fr build/
	rm -fr dist/
	rm -fr *.egg-info

clean-pyc: ## remove Python file artifacts
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +

install: ## create the development environment from uv.lock
	uv sync

lock: ## refresh uv.lock after changing dependencies
	uv lock

lint: ## lint and check formatting with ruff
	uv run ruff check .
	uv run ruff format --check .

typecheck: ## check types with mypy and the django-stubs plugin
	uv run mypy

format: ## apply ruff's automatic fixes and reformat
	uv run ruff check --fix .
	uv run ruff format .

hooks: ## install the pre-commit git hooks
	uv run pre-commit install

pre-commit: ## run every pre-commit hook against the whole tree
	uv run pre-commit run --all-files

test: ## run tests quickly with the default Python
	uv run python runtests.py

test-all: ## run tests on every supported Python and Django version with tox
	uv run tox

bench-db: ## start the PostgreSQL the benchmarks run against
	docker run -d --rm --name sso-bench-pg \
		-e POSTGRES_PASSWORD=postgres -e POSTGRES_USER=postgres -e POSTGRES_DB=postgres \
		-p 55432:5432 postgres:16
	@echo "waiting for postgres..."
	@until docker exec sso-bench-pg pg_isready -q; do sleep 1; done

bench-db-stop: ## stop the benchmark database
	docker stop sso-bench-pg

bench: ## compare query performance against django-tenants (needs bench-db)
	uv run --group bench python -m benchmarks.run

coverage: ## check code coverage quickly with the default Python
	uv run coverage run --source vinta_orgs,vinta_orgs_custom_data runtests.py
	uv run coverage report -m
	uv run coverage html
	$(BROWSER) htmlcov/index.html

DOCS_ENV := uv run --with-requirements docs/requirements.txt

docs: ## generate Sphinx HTML documentation, including API docs
	rm -f docs/modules.rst docs/vinta_orgs*.rst
	$(DOCS_ENV) sphinx-apidoc -o docs/ vinta_orgs vinta_orgs/tests vinta_orgs/migrations
	rm -rf docs/_build
	$(DOCS_ENV) sphinx-build -b html docs docs/_build/html
	$(BROWSER) docs/_build/html/index.html

docs-serve: ## rebuild the docs on change and serve them at localhost:8000
	$(DOCS_ENV) --with sphinx-autobuild sphinx-autobuild docs docs/_build/html

dist: clean ## build the sdist and the wheel
	uv build
	ls -l dist

release: dist ## build and upload a release to PyPI
	uv publish
