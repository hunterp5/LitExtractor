"""Tests for reuse and serialization of the OpenChemIE runtime client."""

from __future__ import annotations

from patentextractor import model_runtime


def test_cached_client_is_reused_until_device_changes(monkeypatch):
    monkeypatch.setattr(model_runtime, "_cached_client", None)
    created: list[tuple[str, object]] = []

    def factory(device: str) -> object:
        client = object()
        created.append((device, client))
        return client

    cpu_client = model_runtime.get_cached_openchemie_client("cpu", lambda: factory("cpu"))
    assert model_runtime.get_cached_openchemie_client("cpu", lambda: factory("cpu")) is cpu_client

    cuda_client = model_runtime.get_cached_openchemie_client("cuda", lambda: factory("cuda"))
    assert cuda_client is not cpu_client
    assert created == [("cpu", cpu_client), ("cuda", cuda_client)]
