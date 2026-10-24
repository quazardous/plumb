# Changelog

All notable changes to this project are documented here: what changed for a user, not how.

## [Unreleased]

## [0.1.0]

- First release: services declared in YAML (`imports`, `parameters`, `services`, `when@<env>`), tied to
  configuration by parameters (`%name%`, interpolation, `%env(NAME)%` with an `env(NAME)` default).
- Services by class or factory (dotted callable, or a method of another service), positional or named
  arguments, references (`@id`, `@?id`), aliases, tags and `!tagged_iterator`, shared or not.
- Autowiring by type hint, through an alias of the type's dotted name or the only service of that type.
- `runtime:` arguments given to `get()`, for values known only when the service is used.
- `compile()` checks every service and parameter and reports all problems at once, circular
  references included; `override()` replaces a service in tests.
