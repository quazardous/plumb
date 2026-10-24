# Changelog

All notable changes to this project are documented here: what changed for a user, not how.

## [Unreleased]

## [0.3.1]

- `Container.override()` nests: leaving an inner override of a service brings back the outer one
  (it used to fail with a `KeyError`).

## [0.3.0]

- `!tagged_locator {tag, index_by}`: inject a lazy registry of tagged services, keyed by a tag attribute;
  it also gives each one's tag attributes and class without building it. `Container.locator()` is the
  same from code.
- `!service_closure '@id'`: inject a callable that builds the service when called, with its runtime
  arguments (an endpoint per account, for instance); overrides apply at call time.

## [0.2.1]

- Published on PyPI as `plumb-q` (`pip install plumb-q`).

## [0.2.0]

- `Container.target(id)` gives what a service is built from (its class or factory), without building it:
  pick a class by tag, then call one of its classmethods.

## [0.1.0]

- First release: services declared in YAML (`imports`, `parameters`, `services`, `when@<env>`), tied to
  configuration by parameters (`%name%`, interpolation, `%env(NAME)%` with an `env(NAME)` default).
- Services by class or factory (dotted callable, or a method of another service), positional or named
  arguments, references (`@id`, `@?id`), aliases, tags and `!tagged_iterator`, shared or not.
- Autowiring by type hint, through an alias of the type's dotted name or the only service of that type.
- `runtime:` arguments given to `get()`, for values known only when the service is used.
- `compile()` checks every service and parameter and reports all problems at once, circular
  references included; `override()` replaces a service in tests.
