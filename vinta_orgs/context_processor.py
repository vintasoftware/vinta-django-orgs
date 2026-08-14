from typing import Any

from django.http import HttpRequest

from vinta_orgs.state import organization_state


def current_organization(request: HttpRequest) -> dict[str, Any]:
    return {
        'organization': organization_state.get(),
    }
