"""A thin, swappable interface over the vendor MinerU client.

`mineru_vl_utils.MinerUClient` builds its own internal `httpx.Client` at construction time with
no injection point for a test transport, and construction itself issues a live request to check
or discover the served model name. Wrapping it behind `PageBlockExtractor` is the same shape this
project already uses for `EmbeddingProvider` (`search/embeddings.py`) and `AnswerProvider`
(`search/rag.py`): jobs depend on the protocol and take a real or fake implementation injected,
so tests never construct the vendor client at all.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

from PIL import Image

from billwatcher.config import Settings

if TYPE_CHECKING:
    from mineru_vl_utils.structs import ContentBlock


class MarkdownExtractorUnavailable(RuntimeError):
    """The MinerU client could not be built or the configured endpoint could not be reached."""


class PageBlockExtractor(Protocol):
    def extract_pages(self, images: Sequence[Image.Image]) -> "list[list[ContentBlock]]": ...


class MineruHttpExtractor:
    """Wraps the vendor client's `http-client` backend against a hosted MinerU server."""

    def __init__(
        self,
        *,
        base_url: str,
        model_name: str = "",
        api_key: str = "",
        timeout_seconds: float = 120.0,
    ) -> None:
        try:
            from mineru_vl_utils import MinerUClient
        except ImportError as error:
            raise MarkdownExtractorUnavailable(
                "the 'mineru-vl-utils' package is not installed"
            ) from error
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        try:
            self._client = MinerUClient(
                backend="http-client",
                server_url=base_url,
                server_headers=headers,
                model_name=model_name or None,
                http_timeout=int(timeout_seconds),
                connect_timeout=min(10, int(timeout_seconds)),
            )
        except Exception as error:
            raise MarkdownExtractorUnavailable(
                f"could not reach the MinerU endpoint at {base_url}: {error}"
            ) from error

    @property
    def model_name(self) -> str:
        # `MinerUClient` (the vendor top-level class we wrap as `self._client`) delegates to an
        # inner backend-specific client at `.client`; that inner client, not the wrapper, is
        # where the resolved or checked model name actually lives.
        return str(self._client.client.model_name)

    def extract_pages(self, images: Sequence[Image.Image]) -> "list[list[ContentBlock]]":
        if not images:
            return []
        result: list[list[ContentBlock]] = self._client.batch_two_step_extract(list(images))
        return result


def build_extractor(settings: Settings) -> PageBlockExtractor:
    """Resolve the configured MinerU endpoint, refusing to invent a default."""
    if not settings.mineru_enabled or not settings.mineru_base_url:
        raise MarkdownExtractorUnavailable(
            "no MinerU endpoint is configured; set MINERU_ENABLED=true and MINERU_BASE_URL"
        )
    return MineruHttpExtractor(
        base_url=settings.mineru_base_url,
        model_name=settings.mineru_model_name,
        api_key=settings.mineru_api_key,
        timeout_seconds=settings.mineru_timeout_seconds,
    )
