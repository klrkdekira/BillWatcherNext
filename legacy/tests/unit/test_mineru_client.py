"""`MineruHttpExtractor` against a faked vendor client, never the real network.

`model_name` is pinned here because it was wrong once: a live smoke test against the real hosted
endpoint (https://mineru.loqasi.io) found that the vendor `MinerUClient` delegates to an inner
backend-specific client at `.client`, and the resolved model name lives on *that* object, not on
`MinerUClient` itself. The bug was invisible to every other test in this file, because they never
construct the real vendor client at all — which is exactly why this one exists.
"""

import pytest

from billwatcher.config import Settings
from billwatcher.mineru.client import (
    MarkdownExtractorUnavailable,
    MineruHttpExtractor,
    build_extractor,
)


class _FakeInnerVlmClient:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name


class _FakeVendorMinerUClient:
    """Mirrors the one structural fact this project depends on: `MinerUClient.client.model_name`."""

    def __init__(self, **_kwargs: object) -> None:
        self.client = _FakeInnerVlmClient(model_name="fake/model/path")


def test_model_name_reads_from_the_vendor_clients_inner_backend(monkeypatch) -> None:
    import mineru_vl_utils

    monkeypatch.setattr(mineru_vl_utils, "MinerUClient", _FakeVendorMinerUClient)
    extractor = MineruHttpExtractor(base_url="https://example.org")
    assert extractor.model_name == "fake/model/path"


def test_a_construction_failure_is_wrapped_as_unavailable(monkeypatch) -> None:
    import mineru_vl_utils

    def _boom(**_kwargs: object) -> None:
        raise RuntimeError("connection refused")

    monkeypatch.setattr(mineru_vl_utils, "MinerUClient", _boom)
    with pytest.raises(MarkdownExtractorUnavailable, match="could not reach"):
        MineruHttpExtractor(base_url="https://example.org")


def test_build_extractor_refuses_when_not_enabled() -> None:
    with pytest.raises(MarkdownExtractorUnavailable, match="MINERU_ENABLED"):
        build_extractor(Settings())


def test_build_extractor_resolves_the_configured_endpoint(monkeypatch) -> None:
    import mineru_vl_utils

    monkeypatch.setattr(mineru_vl_utils, "MinerUClient", _FakeVendorMinerUClient)
    settings = Settings(mineru_enabled=True, mineru_base_url="https://mineru.loqasi.io")
    extractor = build_extractor(settings)
    assert extractor.model_name == "fake/model/path"
