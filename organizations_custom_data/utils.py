from collections.abc import Callable, Sequence
from typing import Any


def compose_list(funcs: Sequence[Callable[[Any], Any]]) -> Callable[[Any], Any]:
    """Chain ``funcs`` right-to-left into a single one-argument callable."""

    def inner(data: Any, funcs: Sequence[Callable[[Any], Any]] = funcs) -> Any:
        return inner(funcs[-1](data), funcs[:-1]) if funcs else data

    return inner
