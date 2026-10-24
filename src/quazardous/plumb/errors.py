"""Errors raised by plumb."""
from __future__ import annotations


class PlumbError(Exception):
    """Base class of every plumb error."""


class DefinitionError(PlumbError):
    """A services file is malformed (unknown key, bad shape)."""


class CompileError(PlumbError):
    """The container does not compile. ``problems`` lists every problem found, not just the first."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("container does not compile:\n  " + "\n  ".join(problems))


class ServiceNotFound(PlumbError, LookupError):
    """No service (or alias) under this id."""


class ParameterNotFound(PlumbError, LookupError):
    """No parameter under this name (neither declared nor given to the builder)."""


class CircularReference(PlumbError):
    """Building a service requires the service itself."""
