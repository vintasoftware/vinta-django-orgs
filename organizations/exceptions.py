from typing import Any


class OrganizationNotFoundError(Exception):
    def __init__(self, message: str = "Organization with this slug couldn't be found", errors: Any = None) -> None:
        super().__init__(message)
