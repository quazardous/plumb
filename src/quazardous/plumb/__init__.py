"""plumb: a Symfony-style service container for Python.

Services are declared in YAML files (``services.yaml``) that tie them to the application's
configuration through parameters; the builder compiles them and reports every problem at once,
before anything runs.

    from quazardous.plumb import ContainerBuilder
    container = ContainerBuilder(parameters=config, env="prod").load("config/services.yaml").compile()
    orders = container.get("app.orders", account="fr")
"""
from quazardous.plumb.container import Container, ContainerBuilder
from quazardous.plumb.definition import Tagged
from quazardous.plumb.errors import (
    CircularReference,
    CompileError,
    DefinitionError,
    ParameterNotFound,
    PlumbError,
    ServiceNotFound,
)

__version__ = "0.2.1"

__all__ = ["CircularReference", "CompileError", "Container", "ContainerBuilder", "DefinitionError",
           "ParameterNotFound", "PlumbError", "ServiceNotFound", "Tagged", "__version__"]
