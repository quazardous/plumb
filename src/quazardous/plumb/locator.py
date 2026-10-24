"""``ServiceLocator``: what ``!tagged_locator`` injects, a lazy registry of tagged services by key."""
from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from quazardous.plumb.container import Container


class ServiceLocator:
    """The services carrying a tag, by key; nothing is built until asked.

    ``locator[key]`` (or ``locator.get(key, **runtime)``) builds or returns the service; ``attributes(key)``
    gives its tag attributes and ``target(key)`` its class, both without building it.
    """

    def __init__(self, container: Container, tag: str, index: dict[str, tuple[str, dict]]):
        self._container = container
        self.tag = tag
        self._index = index

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def get(self, key: str, **runtime: Any) -> Any:
        if key not in self._index:
            raise KeyError(f"no service tagged {self.tag!r} under {key!r} ({', '.join(self._index) or 'none'})")
        return self._container.get(self._index[key][0], **runtime)

    def id(self, key: str) -> str:
        return self._index[key][0]

    def attributes(self, key: str) -> dict:
        return dict(self._index[key][1])

    def target(self, key: str) -> Any:
        return self._container.target(self._index[key][0])

    def keys(self) -> list[str]:
        return list(self._index)

    def __contains__(self, key: object) -> bool:
        return key in self._index

    def __iter__(self) -> Iterator[str]:
        return iter(self._index)

    def __len__(self) -> int:
        return len(self._index)

    def __repr__(self) -> str:
        return f"<ServiceLocator {self.tag!r}: {', '.join(self._index)}>"
