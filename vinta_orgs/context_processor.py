from typing import Any

from django.http import HttpRequest

from vinta_orgs.helpers.organizations import get_current_organization


def current_organization(request: HttpRequest) -> dict[str, Any]:
    return {
        'organization': get_current_organization(),
    }
