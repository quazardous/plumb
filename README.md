# plumb

A **Symfony-style service container** for Python.

Services are declared in YAML files that tie them to the application's configuration through
parameters. The builder compiles the declarations and reports **every** problem at once (missing
class, unknown parameter, dangling reference, impossible autowiring, circular reference) before
anything runs.

```python
from quazardous.plumb import ContainerBuilder

container = ContainerBuilder(parameters=config, env="prod").load("config/services.yaml").compile()
orders = container.get("app.orders", account="fr")
```

One dependency (PyYAML), no framework required. Python 3.10+. MIT.

## Install

```bash
pip install plumb-q        # or: uv add plumb-q
```

The package is `plumb-q` on PyPI; the module is `quazardous.plumb`.

## Why

Python dependency-injection libraries declare services in code (decorators, container classes).
plumb takes Symfony's approach: **the services file is the wiring**, and it reads the configuration.
Code stays free of lookups and of `settings.X` reads; swapping an implementation per environment or
per configuration value is a line in a file, checked at startup.

## A services file

```yaml
imports:
  - providers.yaml                  # relative to this file; later entries win

parameters:
  api.url: 'https://%host%/api'     # %name% → a declared parameter, or one given to the builder
  api.token: '%env(API_TOKEN)%'     # from the environment…
  env(API_TOKEN): ''                # …with this default when it is not set

services:
  _defaults: { autowire: true, shared: true }

  app.transport:
    class: app.transport.HttpTransport
    arguments: { base_url: '%api.url%', token: '%api.token%' }

  app.transport.Transport: '@app.transport'      # alias: an interface → its implementation

  app.orders.v1:
    class: app.orders.Orders
    shared: false
    runtime: [account]                            # given to get(): get("app.orders.v1", account="fr")
    tags: [{ name: orders_source, version: v1 }]

  app.registry:
    class: app.normalizers.Registry
    arguments: [!tagged_iterator normalizer]      # every service tagged normalizer, in order

  app.idp:
    factory: app.identity.provider                # a dotted callable…
    arguments: ['%idp.driver%', '%idp.url%']
  app.client:
    factory: ['@app.client_factory', create]      # …or a method of another service

when@test:
  services:
    app.transport: { class: app.testing.FakeTransport }
```

### Values

| In a value | Means |
|---|---|
| `'%name%'` | the parameter, with its type (a whole-string reference) |
| `'https://%host%/x'` | the parameter interpolated into the string |
| `'%env(NAME)%'` | the environment variable; the parameter `env(NAME)` is its default |
| `'@id'` | the service `id` (or what the alias `id` points to) |
| `'@?id'` | the service, or `None` when it is not declared |
| `!tagged_iterator tag` | the list of the services carrying `tag` |
| `'%%'`, `'@@'` | a literal `%`, a literal `@` |

### A service

| Key | |
|---|---|
| `class` | dotted path of the class; when there is no `class` nor `factory`, the id is the class |
| `factory` | a dotted callable, or `['@service', 'method']` |
| `arguments` | a list (positional) or a mapping (by name) |
| `autowire` | fill the remaining constructor arguments by type hint: the service whose id is the type's dotted name, an alias of that name, or the only service of that type |
| `shared` | one instance for the container (default), or one per `get()` |
| `runtime` | arguments given to `get()` (a value known only when the service is used, such as an account); such a service is built at each `get()` |
| `tags` | `[name]` or `[{name: …, attr: …}]` |
| `alias` | this id is another service (`'@other'` for short) |

## The container

```python
container.get("id", **runtime)                     # build or reuse
container.param("api.url")
container.tagged("orders_source", version="v1")    # ids, filtered by tag attributes
container.tagged_items("orders_source")            # [(id, attributes)]
container.target("app.orders.v1")                  # its class (or factory), without building it
with container.override("app.transport", fake):    # tests
    ...
```

`ContainerBuilder.set(id, obj)` registers an object built elsewhere (a synthetic service).

A typical pattern is choosing an implementation from configuration with tags:

```python
(sid,) = container.tagged("orders_source", version=container.param("orders.api"))
source = container.get(sid, account="fr")
```

## Compile errors

```
quazardous.plumb.errors.CompileError: container does not compile:
  parameter 'p': %missing% is neither declared nor given
  a: ModuleNotFoundError: No module named 'app.nope'  [config/services.yaml]
  b: ServiceNotFound: no service 'ghost'  [config/services.yaml]
  c: ServiceNotFound: cannot autowire argument 'clock' (Clock): declare it, or register a service of that type
  circular reference: x → y → x
```

Call `compile()` where the application starts (for example in a Django `AppConfig.ready()`, and in a
check command): a bad file stops the start, not a request at 3 a.m.

## Coming from Symfony

| Symfony | plumb |
|---|---|
| `services.yaml`, `imports`, `parameters`, `when@env` | same |
| `%param%`, `%env(VAR)%`, `env(VAR)` default parameter | same |
| `@service`, `@?service`, `!tagged_iterator` | same |
| `_defaults: autowire`, alias of an interface | same; types are Python type hints |
| `factory: [@service, method]` | same; also a dotted callable |
| `shared: false` | same |
| — | `runtime:` arguments given to `get()` |
| compiled container | `compile()` checks everything; services are still built lazily |
| `bind`, `calls`, `decorates`, `public`, service locators, expression language | not (yet) |

## Development

```bash
uv run --with pytest --with pyyaml pytest
uv run --with ruff ruff check
cd src && uv run --with mypy --with types-pyyaml python -m mypy --python-version 3.10 \
    --ignore-missing-imports --explicit-package-bases --namespace-packages quazardous/plumb
```
