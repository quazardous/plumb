"""Reading services files into definitions: imports, parameters, services, ``when@<env>`` blocks."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from quazardous.plumb.errors import DefinitionError

SERVICE_KEYS = {"class", "factory", "arguments", "tags", "alias", "shared", "autowire", "runtime"}
DEFAULT_KEYS = {"autowire", "shared"}


@dataclass(frozen=True)
class Tagged:
    """``!tagged_iterator <tag>`` : the list of the services carrying this tag, in declaration order."""
    tag: str


@dataclass(frozen=True)
class TaggedLocator:
    """``!tagged_locator <tag>`` or ``!tagged_locator {tag: <tag>, index_by: <attribute>}``: a lazy
    registry of the services carrying this tag, keyed by the tag attribute ``index_by`` (by id without it)."""
    tag: str
    index_by: str | None = None


@dataclass(frozen=True)
class ServiceClosure:
    """``!service_closure '@id'``: a callable that builds or returns the service when called, with its
    runtime arguments: ``make(account="fr")`` is ``container.get(id, account="fr")``."""
    id: str


@dataclass
class Definition:
    id: str
    class_: str | None = None
    factory: str | list | None = None
    arguments: list | dict = field(default_factory=list)
    tags: list[dict] = field(default_factory=list)
    alias: str | None = None
    shared: bool = True
    autowire: bool = False
    runtime: list[str] = field(default_factory=list)
    source: str = ""


class _Loader(yaml.SafeLoader):
    pass


def _tagged_iterator(loader: _Loader, node: yaml.Node) -> Tagged:
    return Tagged(str(loader.construct_scalar(node)))  # type: ignore[arg-type]


def _tagged_locator(loader: _Loader, node: yaml.Node) -> TaggedLocator:
    if isinstance(node, yaml.ScalarNode):
        return TaggedLocator(str(loader.construct_scalar(node)))
    if isinstance(node, yaml.MappingNode):
        spec = loader.construct_mapping(node)
        if "tag" not in spec or set(spec) - {"tag", "index_by"}:
            raise yaml.constructor.ConstructorError(None, None, "!tagged_locator takes {tag, index_by}",
                                                    node.start_mark)
        index_by = spec.get("index_by")
        return TaggedLocator(str(spec["tag"]), None if index_by is None else str(index_by))
    raise yaml.constructor.ConstructorError(None, None, "!tagged_locator takes a tag or {tag, index_by}",
                                            node.start_mark)


def _service_closure(loader: _Loader, node: yaml.Node) -> ServiceClosure:
    value = str(loader.construct_scalar(node))  # type: ignore[arg-type]
    if not value.startswith("@") or value.startswith(("@@", "@?")):
        raise yaml.constructor.ConstructorError(None, None, "!service_closure takes '@id'", node.start_mark)
    return ServiceClosure(value[1:])


_Loader.add_constructor("!tagged_iterator", _tagged_iterator)
_Loader.add_constructor("!tagged_locator", _tagged_locator)
_Loader.add_constructor("!service_closure", _service_closure)


@dataclass
class Document:
    parameters: dict[str, Any] = field(default_factory=dict)
    services: dict[str, Definition] = field(default_factory=dict)


def load_file(path: Path, env: str, seen: set[Path] | None = None) -> Document:
    """Read a services file and its imports (resolved against the file's folder). Later entries win:
    imports first, then the file, then its ``when@<env>`` block."""
    path = path.resolve()
    seen = set() if seen is None else seen
    if path in seen:
        raise DefinitionError(f"{path}: imported twice (import cycle?)")
    seen.add(path)
    try:
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader) or {}  # noqa: S506 — safe loader subclass
    except yaml.YAMLError as e:
        raise DefinitionError(f"{path}: {e}") from e
    if not isinstance(raw, dict):
        raise DefinitionError(f"{path}: a mapping is expected at the top")
    doc = Document()
    for imp in raw.get("imports") or []:
        name = imp["resource"] if isinstance(imp, dict) else imp
        merge(doc, load_file(path.parent / name, env, seen))
    merge(doc, parse(raw, env, str(path)))
    return doc


def parse(raw: dict, env: str, source: str = "<dict>") -> Document:
    unknown = {k for k in raw if k not in ("imports", "parameters", "services") and not k.startswith("when@")}
    if unknown:
        raise DefinitionError(f"{source}: unknown top-level key(s) {sorted(unknown)}")
    doc = _block(raw, source)
    when = raw.get(f"when@{env}")
    if when:
        if not isinstance(when, dict) or set(when) - {"parameters", "services"}:
            raise DefinitionError(f"{source}: when@{env} takes parameters and services only")
        merge(doc, _block(when, f"{source} (when@{env})"))
    return doc


def merge(into: Document, other: Document) -> None:
    into.parameters.update(other.parameters)
    into.services.update(other.services)


def _block(raw: dict, source: str) -> Document:
    params = raw.get("parameters") or {}
    if not isinstance(params, dict):
        raise DefinitionError(f"{source}: parameters must be a mapping")
    services = dict(raw.get("services") or {})
    defaults = services.pop("_defaults", None) or {}
    if set(defaults) - DEFAULT_KEYS:
        raise DefinitionError(f"{source}: _defaults takes {sorted(DEFAULT_KEYS)} only")
    out = Document(parameters=dict(params))
    for sid, spec in services.items():
        out.services[sid] = _definition(str(sid), spec, defaults, source)
    return out


def _definition(sid: str, spec: Any, defaults: dict, source: str) -> Definition:
    if isinstance(spec, str) and spec.startswith("@"):  # alias shorthand: Some.Interface: '@impl'
        return Definition(sid, alias=spec[1:], source=source)
    spec = {} if spec is None else spec
    if not isinstance(spec, dict):
        raise DefinitionError(f"{source}: service {sid!r} must be a mapping or an '@alias'")
    if set(spec) - SERVICE_KEYS:
        raise DefinitionError(f"{source}: service {sid!r}: unknown key(s) {sorted(set(spec) - SERVICE_KEYS)}")
    if "alias" in spec:
        if set(spec) != {"alias"}:
            raise DefinitionError(f"{source}: service {sid!r}: an alias takes no other key")
        return Definition(sid, alias=str(spec["alias"]).removeprefix("@"), source=source)
    class_ = spec.get("class")
    if class_ is None and "factory" not in spec:
        class_ = sid  # Symfony style: the id is the class
    tags = [{"name": t} if isinstance(t, str) else dict(t) for t in spec.get("tags") or []]
    if any("name" not in t for t in tags):
        raise DefinitionError(f"{source}: service {sid!r}: every tag needs a name")
    args = spec.get("arguments") or []
    if not isinstance(args, (list, dict)):
        raise DefinitionError(f"{source}: service {sid!r}: arguments must be a list or a mapping")
    return Definition(
        sid, class_=class_, factory=spec.get("factory"), arguments=args, tags=tags,
        shared=bool(spec.get("shared", defaults.get("shared", True))),
        autowire=bool(spec.get("autowire", defaults.get("autowire", False))),
        runtime=list(spec.get("runtime") or []), source=source,
    )
