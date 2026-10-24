from pathlib import Path

import pytest

from quazardous.plumb import (
    CircularReference,
    CompileError,
    ContainerBuilder,
    DefinitionError,
    ParameterNotFound,
    ServiceNotFound,
)
from sample.app import FakeTransport, HttpTransport, Normalizer, Orders, OrdersV0

HERE = Path(__file__).parent / "fixtures"
CONFIG = {"host": "shop.example.test", "tls_verify": False, "shop.orders_api": "v1"}


def build(env="prod", environ=None, **config):
    return ContainerBuilder({**CONFIG, **config}, env=env, environ=environ or {}).load(HERE / "main.yaml").compile()


def test_parameters_tie_services_to_configuration():
    c = build()
    t = c.get("app.transport")
    assert isinstance(t, HttpTransport)
    assert (t.base_url, t.verify) == ("https://shop.example.test/api", False)  # interpolated, then typed
    assert c.param("orders.api") == "v1"


def test_shared_by_default_and_runtime_arguments_build_anew():
    c = build()
    assert c.get("app.transport") is c.get("app.transport")
    a, b = c.get("app.orders.v1", account="fr"), c.get("app.orders.v1", account="de")
    assert (a.account, b.account) == ("fr", "de") and a is not b
    with pytest.raises(TypeError, match="must be given"):
        c.get("app.orders.v1")
    with pytest.raises(TypeError, match="not runtime"):
        c.get("app.transport", account="fr")


def test_autowiring_by_type_through_an_interface_alias():
    c = build()
    o = c.get("app.orders.v0", account="fr")
    assert isinstance(o, OrdersV0) and o.transport is c.get("app.transport")
    assert o.page_size == 50 and o.clock is None      # declared argument, and an optional one left alone


def test_tags_choose_by_configuration():
    c = build()
    (sid,) = c.tagged("orders_source", version=c.param("orders.api"))
    assert type(c.get(sid, account="fr")) is Orders
    c0 = build(**{"shop.orders_api": "v0"})
    assert c0.tagged("orders_source", version=c0.param("orders.api")) == ["app.orders.v0"]
    assert c.tagged_items("orders_source")[1] == ("app.orders.v0", {"version": "v0"})


def test_tagged_iterator_injects_every_tagged_service_in_order():
    reg = build().get("app.registry")
    assert [n.version for n in reg.normalizers] == ["v0", "v1"]
    assert all(isinstance(n, Normalizer) for n in reg.normalizers)


def test_factories_escapes_and_env_parameters():
    c = build()
    assert c.get("app.greeting") == "hello nobody@"          # env(PLUMB_USER) default ; '@@' is a literal @
    assert c.get("app.greeting2") == "%prefix: world"         # '%%' is a literal %
    assert build(environ={"PLUMB_USER": "ada"}).get("app.greeting") == "hello ada@"


def test_when_env_overrides_and_override_in_a_test():
    c = build(env="test")
    assert isinstance(c.get("app.transport"), FakeTransport)
    fake = FakeTransport()
    with c.override("sample.app.Transport", fake):              # through the alias
        assert c.get("app.orders.v1", account="fr").transport is fake
    assert c.get("app.transport") is not fake


def test_compile_reports_every_problem_at_once():
    b = ContainerBuilder({}, environ={}).load_dict({
        "parameters": {"p": "%missing%"},
        "services": {
            "a": {"class": "sample.nope.Missing"},
            "b": {"class": "sample.app.Normalizer", "arguments": ["@ghost"]},
            "c": {"class": "sample.app.Needy", "autowire": True},
            "d": {"factory": "sample.app.make_greeting", "arguments": ["%also.missing%"]},
        },
    })
    with pytest.raises(CompileError) as e:
        b.compile()
    text = "\n".join(e.value.problems)
    assert len(e.value.problems) == 5
    for needle in ("parameter 'p'", "a: ModuleNotFoundError", "no service 'ghost'",
                   "cannot autowire argument 'missing'", "%also.missing%"):
        assert needle in text


def test_circular_references_are_found_at_compile_time():
    b = ContainerBuilder().load_dict({"services": {
        "x": {"class": "sample.app.Loop", "arguments": ["@y"]},
        "y": {"class": "sample.app.Loop", "arguments": ["@x"]},
    }})
    with pytest.raises(CompileError, match="circular reference: x → y → x|circular reference: y → x → y"):
        b.compile()


def test_ambiguous_autowiring_asks_for_an_alias():
    b = ContainerBuilder().load_dict({"services": {
        "t1": {"class": "sample.app.FakeTransport"},
        "t2": {"class": "sample.app.FakeTransport"},
        "o": {"class": "sample.app.Orders", "autowire": True, "runtime": ["account"]},
    }})
    with pytest.raises(CompileError, match="several services match"):
        b.compile()


def test_optional_reference_and_synthetic_service():
    clock = object()
    c = ContainerBuilder().set("clock", clock).load_dict({"services": {
        "n": {"class": "sample.app.Registry", "arguments": [["@?nothing", "@clock"]]},
    }}).compile()
    assert c.get("n").normalizers == [None, clock]


def test_the_id_can_be_the_class():
    c = ContainerBuilder().load_dict({"services": {"sample.app.FakeTransport": None}}).compile()
    assert isinstance(c.get("sample.app.FakeTransport"), FakeTransport)


def test_malformed_files_are_refused():
    with pytest.raises(DefinitionError, match="unknown key"):
        ContainerBuilder().load_dict({"services": {"a": {"klass": "x"}}})
    with pytest.raises(DefinitionError, match="unknown top-level"):
        ContainerBuilder().load_dict({"service": {}})
    with pytest.raises(DefinitionError, match="no other key"):
        ContainerBuilder().load_dict({"services": {"a": {"alias": "b", "shared": False}}})


def test_lookup_errors():
    c = build()
    with pytest.raises(ServiceNotFound):
        c.get("nope")
    with pytest.raises(ParameterNotFound):
        c.param("nope")
    with pytest.raises(CompileError, match="alias loop"):
        ContainerBuilder().load_dict({"services": {"a": "@b", "b": "@a"}}).compile()
    loop = ContainerBuilder().load_dict({"parameters": {"x": "%y%", "y": "%x%"}})
    with pytest.raises(CompileError, match="parameter loop"):
        loop.compile()
    assert issubclass(CircularReference, Exception)


def test_target_gives_the_class_without_building():
    c = build()
    assert c.target("app.orders.v0") is OrdersV0
    assert c.target("sample.app.Transport") is HttpTransport          # through the alias
    assert c.target("app.greeting").__name__ == "make_greeting"
    assert c.target("app.greeting2") is None                          # a method of another service


def test_tagged_locator_is_lazy_and_keyed_by_a_tag_attribute():
    from sample.app import Built, Job
    Built.count = 0
    c = build()
    jobs = c.get("app.runner").jobs
    assert sorted(jobs) == ["journal.route", "orders.import"] and len(jobs) == 2 and "orders.import" in jobs
    assert jobs.attributes("orders.import") == {"key": "orders.import", "every": 600}
    assert jobs.target("journal.route") is Built and Built.count == 0     # nothing built yet
    assert isinstance(jobs["orders.import"], Job) and jobs["orders.import"] is c.get("app.job.import")
    assert Built.count == 0
    with pytest.raises(KeyError, match="journal.route, orders.import|orders.import, journal.route"):
        jobs["nope"]
    by_id = c.locator("normalizer")
    assert by_id.keys() == ["app.normalizer.v0", "app.normalizer.v1"]
    assert c.locator("orders_source", index_by="version").get("v0", account="fr").account == "fr"


def test_service_closure_builds_with_runtime_arguments_and_sees_overrides():
    c = build()
    make = c.get("app.runner").make_orders
    a, b = make(account="fr"), make(account="de")
    assert type(a) is Orders and (a.account, b.account) == ("fr", "de")
    fake = object()
    with c.override("app.orders.v1", fake):
        assert make(account="fr") is fake


def test_locator_and_closure_mistakes_are_compile_errors(tmp_path):
    import yaml

    from quazardous.plumb.definition import _Loader

    def compile_problems(text):
        with pytest.raises(CompileError) as e:
            ContainerBuilder().load_dict(yaml.load(text, Loader=_Loader)).compile()  # noqa: S506
        return "\n".join(e.value.problems)

    jobs = """
services:
  a: { class: sample.app.Job, arguments: [x], tags: [{ name: job, key: k }] }
  b: { class: sample.app.Job, arguments: [y], tags: [%s] }
  r: { class: sample.app.Registry, arguments: [!tagged_locator { tag: job, index_by: key }] }
  s: { class: sample.app.Registry, arguments: [!service_closure '@ghost'] }
"""
    text = compile_problems(jobs % "{ name: job, key: k }")
    assert "r: DefinitionError: !tagged_locator job: key 'k' given by both 'a' and 'b'" in text
    assert "s: ServiceNotFound: no service 'ghost'" in text
    assert "service 'b' has no 'key' attribute" in compile_problems(jobs % "job")
    for bad, message in (("!service_closure ghost", "takes '@id'"), ("!tagged_locator {index_by: k}", "tag, index_by")):
        f = tmp_path / "bad.yaml"
        f.write_text(f"services: {{x: {{arguments: [{bad}]}}}}")
        with pytest.raises(DefinitionError, match=message):
            ContainerBuilder().load(f)
