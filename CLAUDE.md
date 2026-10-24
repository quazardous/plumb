# plumb — rules for agents

This repository is meant to be public (MIT): anything committed here is read by strangers.

## English everywhere

Code, comments, docstrings, README, CHANGELOG and commit messages are in English, whatever language
the conversation is in.

## Nothing from a host application

plumb must stay generic. Never commit hostnames, secrets, dev-machine paths (`/home/...`), private
tracker IDs or the vocabulary of an application that uses it. Examples use `app.*`.

## Symfony is the reference

When a feature exists in Symfony's DependencyInjection component, follow its name and behaviour
(keys, value syntax, precedence), and say so in the README table; depart only for a Python reason,
written down there. One dependency (PyYAML); no framework imports in the package.

## Every problem at compile time

A mistake in a services file must surface in `compile()`, with the service id and the file, together
with every other problem, never later at `get()`. A new feature comes with its compile-time check and
a test of it.

## Changelog

Every user-visible change adds a line under `[Unreleased]` in `CHANGELOG.md`, written for a user.

## Commands

See the README, "Development": tests, ruff and mypy must all pass.
