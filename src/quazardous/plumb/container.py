"""The builder (load, compile) and the compiled container (get, tagged, override)."""
from __future__ import annotations

import importlib
import inspect
import os
import re
import typing
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from quazardous.plumb.definition import (
    Definition,
    Document,
    ServiceClosure,
    Tagged,
    TaggedLocator,
    load_file,
    merge,
    parse,
)
from quazardous.plumb.errors import (
    CircularReference,
    CompileError,
    DefinitionError,
    ParameterNotFound,
    ServiceNotFound,
)
from quazardous.plumb.locator import ServiceLocator

_WHOLE = re.compile(r"^%([^%\s]+)%$")
_EMBEDDED = re.compile(r"%%|%([^%\s]+)%")
_ENV = re.compile(r"^env\((\w+)\)$")


def _import(path: str) -> Any:
    module, _, name = path.rpartition(".")
    if not module:
        raise ImportError(f"{path!r} is not a dotted path")
    obj = importlib.import_module(module)
    for part in name.split("."):
        obj = getattr(obj, part)
    return obj


class ContainerBuilder:
    """Collects definitions, then compiles them into a ``Container``.

    ``parameters``: external values the files refer to as ``%name%`` (an application's configuration,
    flattened). ``env``: the environment whose ``when@<env>`` blocks apply.
    """

    def __init__(self, parameters: Mapping[str, Any] | None = None, env: str = "prod",
                 environ: Mapping[str, str] | None = None):
        self.env = env
        self.external = dict(parameters or {})
        self.environ = os.environ if environ is None else environ
        self.doc = Document()

    def load(self, path: str | Path) -> ContainerBuilder:
        merge(self.doc, load_file(Path(path), self.env))
        return self

    def load_dict(self, raw: dict) -> ContainerBuilder:
        merge(self.doc, parse(raw, self.env))
        return self

    def set(self, sid: str, obj: Any) -> ContainerBuilder:
        """Register an already built object as a service (a synthetic service)."""
        self.doc.services[sid] = Definition(sid, source="<set>")
        self._synthetic = {**getattr(self, "_synthetic", {}), sid: obj}
        return self

    def compile(self) -> Container:
        """Resolve and check everything; raise ``CompileError`` listing every problem found."""
        c = Container(self.doc, self.external, self.environ, getattr(self, "_synthetic", {}))
        problems: list[str] = []
        for name in self.doc.parameters:
            try:
                c.param(name)
            except (ParameterNotFound, CircularReference) as e:
                problems.append(f"parameter {name!r}: {e}")
        for d in self.doc.services.values():
            try:
                c._prepare(d)
            except (DefinitionError, ImportError, AttributeError, ServiceNotFound, ParameterNotFound,
                    CircularReference) as e:
                problems.append(f"{d.id}: {type(e).__name__}: {e}  [{d.source}]")
        if not problems:
            problems += c._check_cycles()
        if problems:
            raise CompileError(problems)
        return c


class Container:
    def __init__(self, doc: Document, external: dict, environ: Mapping[str, str], synthetic: dict):
        self._defs = doc.services
        self._params_raw = doc.parameters
        self._external = external
        self._environ = environ
        self._params: dict[str, Any] = {}
        self._instances: dict[str, Any] = dict(synthetic)
        self._synthetic = set(synthetic)
        self._overrides: dict[str, Any] = {}
        self._targets: dict[str, Any] = {}
        self._wiring: dict[str, dict[str, str]] = {}   # service → {ctor argument: autowired service}
        self._building: list[str] = []

    # ---- parameters ------------------------------------------------------------------------------
    def param(self, name: str, _stack: tuple = ()) -> Any:
        if name in self._params:
            return self._params[name]
        if name in _stack:
            raise CircularReference(f"parameter loop: {' → '.join((*_stack, name))}")
        if m := _ENV.match(name):
            if m.group(1) in self._environ:
                return self._environ[m.group(1)]
            if name in self._params_raw:  # Symfony: a parameter env(NAME) is the default
                return self._resolve(self._params_raw[name], (*_stack, name))
            raise ParameterNotFound(f"environment variable {m.group(1)} is not set (no env({m.group(1)}) default)")
        if name in self._params_raw:
            value = self._resolve(self._params_raw[name], (*_stack, name))
        elif name in self._external:
            value = self._external[name]
        else:
            raise ParameterNotFound(f"%{name}% is neither declared nor given")
        self._params[name] = value
        return value

    def _resolve(self, value: Any, stack: tuple = ()) -> Any:
        """Parameters inside a value: ``'%name%'`` keeps the parameter's type, ``'a %b% c'`` interpolates,
        ``'%%'`` is a literal percent; lists and mappings are walked."""
        if isinstance(value, str):
            if m := _WHOLE.match(value):
                return self.param(m.group(1), stack)
            if "%" in value:
                return _EMBEDDED.sub(lambda m: "%" if m.group(0) == "%%" else str(self.param(m.group(1), stack)), value)
            return value
        if isinstance(value, list):
            return [self._resolve(v, stack) for v in value]
        if isinstance(value, dict):
            return {k: self._resolve(v, stack) for k, v in value.items()}
        return value

    # ---- services --------------------------------------------------------------------------------
    def has(self, sid: str) -> bool:
        return sid in self._defs

    def ids(self) -> list[str]:
        return list(self._defs)

    def get(self, sid: str, **runtime: Any) -> Any:
        """The service ``sid``. A shared service is built once; ``runtime`` arguments (declared under
        ``runtime:``) build a new instance every time."""
        sid = self._real_id(sid)
        if sid in self._overrides:
            return self._overrides[sid]
        d = self._defs[sid]
        if extra := set(runtime) - set(d.runtime):
            raise TypeError(f"{sid}: not runtime argument(s) {sorted(extra)} (declare them under runtime:)")
        if missing := set(d.runtime) - set(runtime):
            raise TypeError(f"{sid}: runtime argument(s) {sorted(missing)} must be given to get()")
        if not runtime and sid in self._instances:
            return self._instances[sid]
        if sid in self._building:
            raise CircularReference(" → ".join((*self._building, sid)))
        self._building.append(sid)
        try:
            obj = self._build(d, runtime)
        finally:
            self._building.pop()
        if d.shared and not d.runtime:
            self._instances[sid] = obj
        return obj

    def target(self, sid: str) -> Any:
        """What the service is built from: its class, or its factory callable (aliases followed), without
        building it; ``None`` for a synthetic service or a factory method of another service. Lets an
        application pick a class by tag (for instance to call a classmethod) before any instance exists."""
        return self._targets.get(self._real_id(sid))

    def tagged(self, tag: str, **attrs: Any) -> list[str]:
        """The ids of the services carrying ``tag`` whose attributes match ``attrs``, in declaration order."""
        return [sid for sid, _ in self.tagged_items(tag, **attrs)]

    def tagged_items(self, tag: str, **attrs: Any) -> list[tuple[str, dict]]:
        out = []
        for sid, d in self._defs.items():
            for t in d.tags:
                if t["name"] == tag and all(str(t.get(k)) == str(v) for k, v in attrs.items()):
                    out.append((sid, {k: v for k, v in t.items() if k != "name"}))
        return out

    def locator(self, tag: str, index_by: str | None = None) -> ServiceLocator:
        """The services carrying ``tag``, keyed by the tag attribute ``index_by`` (by id without it), built
        only when asked: what ``!tagged_locator`` injects."""
        return ServiceLocator(self, tag, self._locator_index(TaggedLocator(tag, index_by)))

    @contextmanager
    def override(self, sid: str, obj: Any) -> Iterator[Any]:
        """Replace a service for the time of a ``with`` block (tests)."""
        sid = self._real_id(sid)
        self._overrides[sid] = obj
        try:
            yield obj
        finally:
            del self._overrides[sid]

    # ---- internals -------------------------------------------------------------------------------
    def _locator_index(self, loc: TaggedLocator) -> dict[str, tuple[str, dict]]:
        index: dict[str, tuple[str, dict]] = {}
        for sid, attrs in self.tagged_items(loc.tag):
            if loc.index_by is None:
                key = sid
            elif loc.index_by in attrs:
                key = str(attrs[loc.index_by])
            else:
                raise DefinitionError(f"!tagged_locator {loc.tag}: service {sid!r} has no {loc.index_by!r} "
                                      "attribute on its tag")
            if key in index:
                raise DefinitionError(f"!tagged_locator {loc.tag}: key {key!r} given by both "
                                      f"{index[key][0]!r} and {sid!r}")
            index[key] = (sid, attrs)
        return index

    def _real_id(self, sid: str, _seen: tuple = ()) -> str:
        d = self._defs.get(sid)
        if d is None:
            raise ServiceNotFound(f"no service {sid!r}")
        if d.alias is None:
            return sid
        if sid in _seen:
            raise CircularReference(f"alias loop: {' → '.join((*_seen, sid))}")
        return self._real_id(d.alias, (*_seen, sid))

    def _prepare(self, d: Definition) -> None:
        """Import the target, check every argument and work out the autowiring, without building."""
        if d.alias is not None:
            self._real_id(d.id)
            return
        if d.id in self._synthetic:
            return
        if d.factory is not None:
            if isinstance(d.factory, list):
                if len(d.factory) != 2 or not str(d.factory[0]).startswith("@"):
                    raise DefinitionError("factory: a dotted callable, or ['@service', 'method']")
                self._real_id(d.factory[0][1:])
                target = None
            else:
                target = _import(d.factory)
        else:
            target = _import(d.class_ or d.id)
        self._targets[d.id] = target
        args = d.arguments
        for v in args if isinstance(args, list) else args.values():
            self._check_value(v)
        self._wiring[d.id] = self._autowire(d, target) if d.autowire and inspect.isclass(target) else {}

    def _check_value(self, v: Any) -> None:
        if isinstance(v, Tagged):
            return
        if isinstance(v, ServiceClosure):
            self._real_id(v.id)
            return
        if isinstance(v, TaggedLocator):
            self._locator_index(v)
            return
        if isinstance(v, str) and v.startswith("@") and not v.startswith("@@"):
            if not v.startswith("@?"):
                self._real_id(v[1:])
            return
        if isinstance(v, list):
            for x in v:
                self._check_value(x)
        elif isinstance(v, dict):
            for x in v.values():
                self._check_value(x)
        else:
            self._resolve(v)

    def _autowire(self, d: Definition, cls: type) -> dict[str, str]:
        params = _ctor_params(cls)
        given = set(d.arguments) if isinstance(d.arguments, dict) else set(list(params)[: len(d.arguments)])
        try:
            hints = typing.get_type_hints(cls.__init__)  # type: ignore[misc]
        except Exception:  # noqa: BLE001 — unresolvable annotations: no autowiring from them
            hints = {}
        wiring = {}
        for name, p in params.items():
            if name in given or name in d.runtime:
                continue
            ref = self._service_for_type(hints.get(name))
            if ref is not None:
                wiring[name] = ref
            elif p.default is inspect.Parameter.empty:
                raise ServiceNotFound(f"cannot autowire argument {name!r} ({_type_name(hints.get(name))}): "
                                      "declare it, or register a service of that type")
        return wiring

    def _service_for_type(self, hint: Any) -> str | None:
        if not inspect.isclass(hint):
            return None
        fqn = f"{hint.__module__}.{hint.__qualname__}"
        if fqn in self._defs:
            return fqn
        matches = [sid for sid, d in self._defs.items()
                   if d.alias is None and inspect.isclass(self._targets.get(sid) or _safe_import(d))
                   and issubclass(self._targets.get(sid) or _safe_import(d), hint)]
        if len(matches) > 1:
            raise ServiceNotFound(f"{fqn}: several services match ({', '.join(matches)}); "
                                  f"declare an alias {fqn}: '@one-of-them'")
        return matches[0] if matches else None

    def _check_cycles(self) -> list[str]:
        graph = {sid: set(self._deps(d)) for sid, d in self._defs.items()}
        problems, state = [], {}

        def visit(n: str, path: list[str]) -> None:
            state[n] = 1
            for m in graph.get(n, ()):
                if state.get(m) == 1:
                    problems.append("circular reference: " + " → ".join(path[path.index(m):] + [m]))
                elif m not in state:
                    visit(m, path + [m])
            state[n] = 2

        for n in graph:
            if n not in state:
                visit(n, [n])
        return problems

    def _deps(self, d: Definition) -> Iterator[str]:
        if d.alias is not None:
            yield d.alias
            return
        if isinstance(d.factory, list):
            yield d.factory[0][1:]

        def walk(v: Any) -> Iterator[str]:
            if isinstance(v, Tagged):
                yield from self.tagged(v.tag)
            elif isinstance(v, str) and v.startswith("@") and not v.startswith("@@"):
                ref = v[2:] if v.startswith("@?") else v[1:]
                if ref in self._defs:
                    yield ref
            elif isinstance(v, (list, tuple)):
                for x in v:
                    yield from walk(x)
            elif isinstance(v, dict):
                for x in v.values():
                    yield from walk(x)

        yield from walk(d.arguments)
        yield from self._wiring.get(d.id, {}).values()

    def _build(self, d: Definition, runtime: dict) -> Any:
        args = d.arguments
        pos = [self._value(v) for v in args] if isinstance(args, list) else []
        kw = {k: self._value(v) for k, v in args.items()} if isinstance(args, dict) else {}
        for name, ref in self._wiring.get(d.id, {}).items():
            kw[name] = self.get(ref)
        if isinstance(d.factory, list):
            target = getattr(self.get(d.factory[0][1:]), d.factory[1])
        else:
            target = self._targets[d.id]
        return target(*pos, **kw, **runtime)

    def _value(self, v: Any) -> Any:
        if isinstance(v, Tagged):
            return [self.get(sid) for sid in self.tagged(v.tag)]
        if isinstance(v, TaggedLocator):
            return ServiceLocator(self, v.tag, self._locator_index(v))
        if isinstance(v, ServiceClosure):
            sid = v.id
            return lambda **runtime: self.get(sid, **runtime)
        if isinstance(v, str) and v.startswith("@@"):
            return v[1:]
        if isinstance(v, str) and v.startswith("@?"):
            return self.get(v[2:]) if self.has(v[2:]) else None
        if isinstance(v, str) and v.startswith("@"):
            return self.get(v[1:])
        if isinstance(v, list):
            return [self._value(x) for x in v]
        if isinstance(v, dict):
            return {k: self._value(x) for k, x in v.items()}
        return self._resolve(v)


def _ctor_params(cls: type) -> dict[str, inspect.Parameter]:
    try:
        sig = inspect.signature(cls)
    except (TypeError, ValueError):
        return {}
    return {n: p for n, p in sig.parameters.items() if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)}


def _safe_import(d: Definition) -> Any:
    if d.factory is not None or d.alias is not None:
        return None
    try:
        return _import(d.class_ or d.id)
    except (ImportError, AttributeError):
        return None


def _type_name(hint: Any) -> str:
    return getattr(hint, "__qualname__", None) or ("no type hint" if hint is None else str(hint))
