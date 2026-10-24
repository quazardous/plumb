"""plumb: a Symfony-style service container for Python.

Services are declared in YAML files (``services.yaml``) that tie them to the application's
configuration through parameters; the builder compiles them and reports every problem at once,
before anything runs.

    from quazardous.plumb import ContainerBuilder
    container = ContainerBuilder(parameters=config, env="prod").load("config/services.yaml").compile()
    orders = container.get("app.orders", account="fr")
"""
from quazardous.plumb.container import Container, ContainerBuilder
from quazardous.plumb.definition import ServiceClosure, Tagged, TaggedLocator
from quazardous.plumb.errors import (
    CircularReference,
    CompileError,
    DefinitionError,
    ParameterNotFound,
    PlumbError,
    ServiceNotFound,
)
from quazardous.plumb.locator import ServiceLocator

__version__ = "0.3.1"

__all__ = ["CircularReference", "CompileError", "Container", "ContainerBuilder", "DefinitionError",
           "ParameterNotFound", "PlumbError", "ServiceClosure", "ServiceLocator", "ServiceNotFound", "Tagged",
           "TaggedLocator", "__version__"]
