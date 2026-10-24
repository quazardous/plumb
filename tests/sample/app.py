"""A small application used by the tests."""
from __future__ import annotations

from abc import ABC, abstractmethod


class Transport(ABC):
    @abstractmethod
    def send(self, what: str) -> str: ...


class HttpTransport(Transport):
    def __init__(self, base_url: str, verify: bool = True):
        self.base_url, self.verify = base_url, verify

    def send(self, what: str) -> str:
        return f"GET {self.base_url}/{what}"


class FakeTransport(Transport):
    def send(self, what: str) -> str:
        return f"fake {what}"


class Clock:
    pass


class Orders:
    def __init__(self, transport: Transport, account: str, clock: Clock | None = None, page_size: int = 100):
        self.transport, self.account, self.clock, self.page_size = transport, account, clock, page_size


class OrdersV0(Orders):
    pass


class Normalizer:
    def __init__(self, version: str):
        self.version = version


class Registry:
    def __init__(self, normalizers: list):
        self.normalizers = normalizers


class Needy:
    def __init__(self, missing: Clock):
        self.missing = missing


class Loop:
    def __init__(self, other):
        self.other = other


def make_greeting(name: str, punctuation: str = "!") -> str:
    return f"hello {name}{punctuation}"


class Factory:
    def __init__(self, prefix: str):
        self.prefix = prefix

    def create(self, name: str) -> str:
        return self.prefix + name
