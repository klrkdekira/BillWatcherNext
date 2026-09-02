"""The configuration gates that protect an operator's decisions, and the defaults that stand in
for one nobody has made yet."""

from pathlib import Path

import pytest

from billwatcher.config import Settings, SitePrefixError, normalise_prefix

PRODUCTION = dict(environment="production", contact_email="ops@example.my")


def test_the_defaults_publish_nothing_and_republish_no_text() -> None:
    """The defaults are the decision. A published tree may be mirrored and cannot be withdrawn.

    An operator who deploys without reading a line of documentation must end up publishing
    nothing, and — if they turn publication on — publishing structure rather than the document's
    own words.
    """
    settings = Settings()
    assert settings.publish_rights_confirmed is False
    assert settings.full_text_rights_confirmed is False
    assert settings.publication_mode == "metadata"
    assert settings.download_enabled is False


def test_the_two_rights_confirmations_stay_separate_questions() -> None:
    """Publishing a reading of the law and republishing the document's words are different
    reviews (ADR-004, ADR-018), so neither confirmation may stand in for the other."""
    assert set(Settings.model_fields) >= {"publish_rights_confirmed", "full_text_rights_confirmed"}
    confirmed = Settings(publish_rights_confirmed=True)
    assert confirmed.full_text_rights_confirmed is False


def test_the_roots_default_beside_the_repository_not_inside_someones_home() -> None:
    """The field defaults, not an instance's: conftest pins both into tmp_path for every test, so
    reading them off an instance would assert the fixture rather than the default."""
    assert Settings.model_fields["corpus_root"].default == Path("corpus")
    assert Settings.model_fields["site_root"].default == Path("docs")


def test_a_pasted_prefix_is_reduced_to_the_bare_host_cname_needs() -> None:
    for given in (
        "bills.engineers.my",
        "https://bills.engineers.my",
        "http://bills.engineers.my/",
        "  Bills.Engineers.MY/  ",
    ):
        assert normalise_prefix(given) == "bills.engineers.my"
    assert Settings(site_prefix="https://bills.example.my/").site_prefix == "bills.example.my"


def test_a_prefix_that_is_not_a_bare_host_is_refused_rather_than_written_to_cname() -> None:
    """An unusable prefix must fail at load. Written into `CNAME` it detaches the live domain, and
    it is also the base of every published FRBR IRI, which a mirror cannot be asked to un-publish.
    """
    for given in ("", "   ", "localhost", "bills.engineers.my:8080", "bills.example.my/bad//path"):
        with pytest.raises(SitePrefixError):
            normalise_prefix(given)
        with pytest.raises(ValueError):
            Settings(site_prefix=given)


def test_a_path_hosted_prefix_keeps_its_path_and_claims_no_cname() -> None:
    """A Pages *project* repository serves under a path (`cheeleong.dev/data-parlimen`). Its IRIs
    hang off the full prefix, and it must not write a `CNAME` — the domain belongs to whatever
    serves the root."""
    settings = Settings(site_prefix="https://cheeleong.dev/data-parlimen/")
    assert settings.site_prefix == "cheeleong.dev/data-parlimen"
    assert settings.site_base_url == "https://cheeleong.dev/data-parlimen"
    assert settings.cname_host is None
    assert settings.site_base_path == "/data-parlimen/"

    apex = Settings(site_prefix="bills.engineers.my")
    assert apex.cname_host == "bills.engineers.my"
    assert apex.site_base_path == "/"


def test_the_published_base_iri_has_no_doubled_separator() -> None:
    """Every published FRBR IRI is this base concatenated with a path from `billwatcher.frbr`.

    A doubled separator names a URL the site does not serve, and unlike a broken page an N-Quads
    file that is already mirrored cannot be corrected. Deriving the base from the validated bare
    hostname is what makes the failure unreachable rather than merely unlikely.
    """
    from billwatcher.frbr import WorkIdentity

    identity = WorkIdentity(doc_type="bill", chamber_code="dr", year=2026, number=15)
    base = Settings(site_prefix="https://bills.example.my/").site_base_url

    assert base == "https://bills.example.my"
    assert base + identity.work_uri == "https://bills.example.my/akn/my/bill/dr/2026/15"
    assert "//akn/" not in base + identity.work_uri


def test_production_refuses_the_placeholder_contact_address() -> None:
    """The address is published in the crawler's user agent; a placeholder there is unreachable."""
    with pytest.raises(ValueError, match="placeholder"):
        Settings(environment="production")
    assert Settings(**PRODUCTION).contact_email == "ops@example.my"


def test_the_crawl_delay_cannot_be_turned_down_below_the_promise() -> None:
    """`DOWNLOAD_DELAY_SECONDS` is a statement about the load Parliament sees, not a tuning knob."""
    with pytest.raises(ValueError):
        Settings(download_delay_seconds=0.1)
    assert Settings(download_delay_seconds=5).download_delay_seconds == 5


def test_an_empty_ca_bundle_variable_means_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """`.env.example` ships `UPSTREAM_CA_BUNDLE=` empty; that must load, not refuse to.

    Reading it as `Path("")` — which normalises to `.` — made every command fail on a `.env` the
    project's own setup had just written.
    """
    monkeypatch.setenv("UPSTREAM_CA_BUNDLE", "")
    assert Settings().upstream_ca_bundle is None
    monkeypatch.setenv("UPSTREAM_CA_BUNDLE", "   ")
    assert Settings().upstream_ca_bundle is None


def test_a_ca_bundle_that_names_no_file_is_still_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPSTREAM_CA_BUNDLE", "/nonexistent/bundle.pem")
    with pytest.raises(ValueError, match="does not name a file"):
        Settings()
