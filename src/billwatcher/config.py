"""Every setting this pipeline has, and the invariants that make a bad one fail at load.

The list is short on purpose. A setting exists here when an operator has a real decision to make —
where the corpus lives, what may be published, how hard to lean on Parliament's server — and not
merely because a value appears twice in the code. Anything derived is derived at the call site.

Validation happens on load rather than at first use, so a configuration that cannot work is an
error before the first request goes out rather than fifty minutes into a download.
"""

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# A bare DNS hostname, which is what GitHub Pages requires in `CNAME`: no scheme, no port,
# and at least one dot, so `localhost` is refused rather than written into a live domain file.
_HOSTNAME = re.compile(
    r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?"
    r"(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$"
)

# One path segment of a path-hosted site: what a GitHub Pages project repository is served under.
_PATH_SEGMENT = re.compile(r"^[a-z0-9]([a-z0-9._-]*[a-z0-9])?$")

RepresentationSet = Literal["jsonld", "semantic", "markdown", "markdown-semantic", "all"]
PublicationMode = Literal["metadata", "full"]


class SitePrefixError(ValueError):
    """The configured prefix is not a hostname (optionally path-suffixed) the site can claim."""


def normalise_prefix(prefix: str) -> str:
    """Reduce an operator-supplied prefix to `host` or `host/path`, the base every IRI hangs off.

    A scheme or a trailing slash is a natural thing to paste and harmless to accept, so both are
    stripped rather than rejected. The host part must be a real hostname; a path part is allowed
    because a tree served by a Pages *project* repository lives under one
    (`cheeleong.dev/data-parlimen`) — such a tree gets no `CNAME`, since the domain belongs to
    whatever serves the root. A port or an empty string is still refused.
    """
    candidate = prefix.strip().lower()
    for scheme in ("https://", "http://"):
        if candidate.startswith(scheme):
            candidate = candidate[len(scheme) :]
    candidate = candidate.rstrip("/")
    host, _, path = candidate.partition("/")
    if not _HOSTNAME.match(host):
        raise SitePrefixError(
            f"SITE_PREFIX must start with a bare hostname such as bills.engineers.my, "
            f"not {prefix!r}"
        )
    if path and not all(_PATH_SEGMENT.match(segment) for segment in path.split("/")):
        raise SitePrefixError(
            f"SITE_PREFIX's path must be plain segments such as data-parlimen, not {prefix!r}"
        )
    return candidate


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"
    # Named in the crawler's user agent so Parliament can reach a person about a request.
    contact_email: str = "operator@example.org"

    # --- where things live -------------------------------------------------------------------
    # The corpus: listings, bills, PDFs, markdown, structures, provenance, manifests. This *is*
    # the record — not a projection of a database — and it is never committed.
    corpus_root: Path = Path("corpus")
    # The published tree GitHub Pages serves from this repository's `docs/`. Shared between two
    # writers: `billwatcher publish` owns the dataset entries, the Vite build owns the frontend.
    # Each reconciles only what it owns, so neither deletes the other's files.
    site_root: Path = Path("docs")

    # --- what the published tree says about itself -------------------------------------------
    # The custom domain Pages answers on. Written verbatim into `CNAME`, and the base of every
    # published FRBR IRI, so a citation in the dataset dereferences to the page that serves it.
    site_prefix: str = "bills.engineers.my"
    # Which representations the published dataset carries. Markdown is the reading, JSON-LD is the
    # graph a consumer can use without an XML toolchain; `all` adds Akoma Ntoso XML and N-Quads.
    site_representations: RepresentationSet = "markdown-semantic"
    # Reuse terms for the project's *own* output. Empty by default and deliberately not guessed: a
    # licence is a grant the owner makes, not a default a tool picks.
    site_licence: str = ""
    site_licence_url: str = ""

    # --- the publication boundary ------------------------------------------------------------
    # `metadata` publishes structure only — FRBR IRIs, provision numbers, headings, and the
    # relationships between them. `full` adds the text of the provisions, which is a separate and
    # separately confirmed decision. An enumeration rather than a boolean so the safe value is the
    # default rather than the negation of a flag.
    publication_mode: PublicationMode = "metadata"
    # Publishing at all. A published tree may be mirrored and cannot be withdrawn (ADR-029), so
    # this is asserted by an operator rather than defaulted, in every environment.
    publish_rights_confirmed: bool = False
    # Publishing the source document's own words, which is the higher bar of the two and covers
    # both `PUBLICATION_MODE=full` and publishing markdown at all (ADR-004, ADR-018, ADR-036).
    full_text_rights_confirmed: bool = False

    # --- gates -------------------------------------------------------------------------------
    # Gate P1's one statistical threshold: the fraction of the source markdown's distinct words
    # that must appear somewhere in the provision tree read out of it. Configurable rather than
    # hard-coded because it is a judgement about a corpus, not a fact about the format.
    structure_gate_min_text_coverage: float = Field(default=0.95, ge=0.0, le=1.0)

    # --- the one stage that touches the network ----------------------------------------------
    download_enabled: bool = False
    # Floored at two seconds in `CrawlPolicy` as well: this is a promise about the load Parliament
    # sees, so it is not a knob that can be turned down to nothing.
    download_delay_seconds: float = Field(default=2.0, ge=2.0)
    document_max_bytes: int = 104_857_600
    # An explicit trust store for upstream requests. Use it when the site serves an incomplete
    # certificate chain: put the missing intermediate in a bundle and point this at it. There is
    # deliberately no setting that disables verification.
    upstream_ca_bundle: Path | None = None

    @property
    def site_base_url(self) -> str:
        """The absolute base of every published FRBR IRI, derived rather than configured twice."""
        return f"https://{self.site_prefix}"

    @property
    def cname_host(self) -> str | None:
        """The hostname `CNAME` should claim, or `None` for a path-hosted tree.

        GitHub Pages reads `CNAME` only on the repository that serves the domain's root. A tree
        published under a path (`cheeleong.dev/data-parlimen`) must not carry one — it would try
        to detach the domain from whatever serves `cheeleong.dev` itself.
        """
        host, _, path = self.site_prefix.partition("/")
        return None if path else host

    @property
    def site_base_path(self) -> str:
        """The path the published tree is served under: `/` at a domain root, else `/<path>/`."""
        _, _, path = self.site_prefix.partition("/")
        return f"/{path}/" if path else "/"

    @field_validator("site_prefix", mode="before")
    @classmethod
    def reduce_the_prefix_to_a_bare_hostname(cls, value: object) -> object:
        """A prefix that is not a hostname must fail here, not in the `CNAME` it would break."""
        if isinstance(value, str):
            return normalise_prefix(value)
        return value

    @field_validator("upstream_ca_bundle", mode="before")
    @classmethod
    def treat_an_empty_variable_as_unset(cls, value: object) -> object:
        """`UPSTREAM_CA_BUNDLE=` means "no bundle", not "a bundle at the empty path".

        `.env.example` ships the variable empty, because it names a decision an operator has to
        make rather than a default. Without this, pydantic reads the empty string as `Path("")` —
        which normalises to `.` — and the check below then refuses to load *any* configuration.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def reject_unreadable_ca_bundle(self) -> "Settings":
        if self.upstream_ca_bundle is not None and not self.upstream_ca_bundle.is_file():
            raise ValueError(f"UPSTREAM_CA_BUNDLE does not name a file: {self.upstream_ca_bundle}")
        return self

    @model_validator(mode="after")
    def reject_production_placeholders(self) -> "Settings":
        if self.environment == "production" and "example.org" in self.contact_email:
            raise ValueError("production configuration contains placeholder values")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
