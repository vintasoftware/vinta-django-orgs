from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from organizations.helpers.organizations import create_organization


class Command(BaseCommand):
    help = 'Creates a new Organization'

    def handle(self, *args: Any, **options: Any) -> None:
        name = input('Enter the Organization name: ')
        slug = input('Enter the Organization slug: (%s)' % slugify(name))
        domain = input('Enter the Organization site: (localhost:8000)')

        if not slug:
            slug = slugify(name)

        if not domain:
            domain = 'localhost:8000'

        with transaction.atomic():
            create_organization(name, slug, [domain])

            self.stdout.write(self.style.SUCCESS('Successfully created Organization %s' % name))
