"""Offline acceptance tests for the GitHub Pages site tree (HANDOFF 28.13, ADR-033)."""

import json

import pytest

from billwatcher.pipeline.export import StaticExportRefused
from billwatcher.pipeline.redact import contains_provision_text
from billwatcher.pipeline.site import SitePrefixError, build_site, normalise_prefix
from billwatcher.pipeline.store import FileStore
from tests.unit.test_pipeline_export import bill, exported_files, seed


def test_the_site_carries_the_semantic_files_and_the_pages_metadata(tmp_path) -> None:
    """The three site files plus "the semantic files such as jsonld and rdf" (ADR-033)."""
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    root = tmp_path / "dist"

    result = build_site(store, site_root=root, prefix="bills.engineers.my", publication_mode="full")

    assert result.counts["exported"] == 1
    files = exported_files(root)
    assert {
        "index.html",
        "CNAME",
        ".nojekyll",
        "index.json",
        "checksums.sha256",
        "akn/my/bill/dr/2026/15/msa@.jsonld",
        "akn/my/bill/dr/2026/15/msa@.nq",
        "definitions/jsonld-context.jsonld",
    } <= files
    # "the semantic files": the two RDF serialisations, not the Akoma Ntoso XML.
    assert not any(path.endswith(".xml") for path in files if path.startswith("akn/"))
    assert (root / "CNAME").read_text(encoding="utf-8") == "bills.engineers.my\n"
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    assert index["representations"] == ["jsonld", "nq"]


def test_the_landing_page_names_the_domain_and_lists_every_published_expression(tmp_path) -> None:
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-a")
    seed(store, record=bill(16), doc_key="doc-b")
    root = tmp_path / "dist"

    build_site(store, site_root=root, prefix="bills.engineers.my", publication_mode="full")

    page = (root / "index.html").read_text(encoding="utf-8")
    assert '<link rel="canonical" href="https://bills.engineers.my/">' in page
    for number in (15, 16):
        assert f"/akn/my/bill/dr/2026/{number}" in page
        assert f"Rang Undang-Undang Contoh {number}" in page
    assert page.count('<a href="/akn/') == 4  # two Expressions x jsonld + nq
    assert page.startswith("<!doctype html>")
    # Every file the page links must exist, or the release ships dead links.
    assert "/definitions/jsonld-context.jsonld" in page
    assert (root / "definitions/jsonld-context.jsonld").exists()


def test_a_title_from_the_corpus_cannot_inject_markup_into_the_landing_page(tmp_path) -> None:
    """Titles are upstream text. The page escapes them rather than trusting Parliament's HTML."""
    store = FileStore(tmp_path / "store")
    record = bill(15)
    record["titles"]["raw_ms"] = 'Rang <script>alert("x")</script> & Co'
    seed(store, record=record, doc_key="doc-passing")
    root = tmp_path / "dist"

    build_site(store, site_root=root, prefix="bills.engineers.my", publication_mode="full")

    page = (root / "index.html").read_text(encoding="utf-8")
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page and "&amp; Co" in page


def test_a_rebuild_over_an_unchanged_store_writes_nothing(tmp_path) -> None:
    """The page must be deterministic — no build timestamp — or every rebuild is a commit."""
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    root = tmp_path / "dist"
    build_site(store, site_root=root, prefix="bills.engineers.my", publication_mode="full")
    before = {
        path: ((root / path).read_bytes(), (root / path).stat().st_mtime_ns)
        for path in exported_files(root)
    }

    result = build_site(store, site_root=root, prefix="bills.engineers.my", publication_mode="full")

    assert result.counts["written"] == 0
    assert result.counts["removed"] == 0
    for path, (payload, mtime) in before.items():
        assert (root / path).read_bytes() == payload
        assert (root / path).stat().st_mtime_ns == mtime


def test_building_into_a_checkout_of_the_publishing_repo_spares_its_files(tmp_path) -> None:
    """The site root *is* another repo's working tree, so this is the normal case, not an edge."""
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    root = tmp_path / "dist"
    build_site(store, site_root=root, prefix="bills.engineers.my", publication_mode="full")

    foreign = {
        ".git/config": b"[core]\n",
        ".git/HEAD": b"ref: refs/heads/gh-pages\n",
        "README.md": b"# Published corpus\n",
        "LICENSE": b"CC BY 4.0\n",
        ".github/workflows/keep.yml": b"name: keep\n",
    }
    for relative, payload in foreign.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    result = build_site(store, site_root=root, prefix="bills.engineers.my", publication_mode="full")

    assert result.counts["removed"] == 0
    for relative, payload in foreign.items():
        assert (root / relative).read_bytes() == payload, relative


def test_a_changed_prefix_rewrites_only_what_names_the_domain(tmp_path) -> None:
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    root = tmp_path / "dist"
    build_site(store, site_root=root, prefix="bills.engineers.my", publication_mode="full")
    jsonld = (root / "akn/my/bill/dr/2026/15/msa@.jsonld").read_bytes()

    result = build_site(store, site_root=root, prefix="corpus.example.my", publication_mode="full")

    # index.html, CNAME and checksums.sha256 — the dataset itself does not depend on the domain.
    assert result.counts["written"] == 3
    assert result.counts["removed"] == 0
    assert (root / "CNAME").read_text(encoding="utf-8") == "corpus.example.my\n"
    assert (root / "akn/my/bill/dr/2026/15/msa@.jsonld").read_bytes() == jsonld


def test_the_site_redacts_at_the_publication_boundary_like_every_other_surface(tmp_path) -> None:
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    root = tmp_path / "dist"

    build_site(store, site_root=root, prefix="bills.engineers.my", publication_mode="metadata")

    for extension in ("jsonld", "nq"):
        payload = (root / f"akn/my/bill/dr/2026/15/msa@.{extension}").read_bytes()
        assert contains_provision_text(payload) is False
        assert b"Seseorang hendaklah melaporkan" not in payload


def test_a_rejected_reading_is_absent_from_the_site_too(tmp_path) -> None:
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    seed(store, record=bill(16), doc_key="doc-rejected", gate_status="mismatch", promote=False)
    root = tmp_path / "dist"

    result = build_site(store, site_root=root, prefix="bills.engineers.my", publication_mode="full")

    assert result.counts["exported"] == 1
    assert result.counts["skipped_rejected"] == 1
    assert not (root / "akn/my/bill/dr/2026/16").exists()
    assert "/akn/my/bill/dr/2026/16" not in (root / "index.html").read_text(encoding="utf-8")


def test_no_site_file_is_a_source_pdf(tmp_path) -> None:
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    root = tmp_path / "dist"

    build_site(store, site_root=root, prefix="bills.engineers.my", publication_mode="full")

    for path in root.rglob("*"):
        if path.is_file():
            assert path.suffix.lower() != ".pdf"
            assert not path.read_bytes().startswith(b"%PDF-")


def test_every_site_file_is_named_in_the_checksum_manifest_and_verifies(tmp_path) -> None:
    import hashlib

    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    root = tmp_path / "dist"

    build_site(store, site_root=root, prefix="bills.engineers.my", publication_mode="full")

    named = {}
    for line in (root / "checksums.sha256").read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        named[relative] = digest
    # index.html and CNAME are published files, so a mirror must be able to verify them too.
    assert "index.html" in named and "CNAME" in named and ".nojekyll" in named
    assert "checksums.sha256" not in named
    assert set(named) == exported_files(root) - {"checksums.sha256"}
    for relative, digest in named.items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("bills.engineers.my", "bills.engineers.my"),
        ("https://bills.engineers.my", "bills.engineers.my"),
        ("http://bills.engineers.my/", "bills.engineers.my"),
        ("  Bills.Engineers.MY/  ", "bills.engineers.my"),
    ],
)
def test_a_pasted_prefix_is_reduced_to_the_bare_host_cname_needs(given, expected) -> None:
    assert normalise_prefix(given) == expected


@pytest.mark.parametrize(
    "given",
    ["", "   ", "localhost", "bills.engineers.my/corpus", "bills.engineers.my:8080", "not a host"],
)
def test_a_prefix_that_is_not_a_bare_host_is_refused_rather_than_written_to_cname(given) -> None:
    with pytest.raises(SitePrefixError):
        normalise_prefix(given)


def test_the_site_command_refuses_without_the_corpus_rights_confirmation(
    tmp_path, monkeypatch
) -> None:
    """Same hardness as export-static: the site is the more public of the two surfaces.

    The roots are pinned explicitly, as the `export-static` command tests do. Without that this
    test is one environment variable away from building the real corpus into the real `dist/`.
    """
    from typer.testing import CliRunner

    from billwatcher.config import get_settings
    from billwatcher.pipeline.cli import app

    monkeypatch.setenv("PIPELINE_DATA_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("PIPELINE_SITE_ROOT", str(tmp_path / "dist"))
    get_settings.cache_clear()

    result = CliRunner().invoke(app, ["build-site"])

    assert result.exit_code == 2
    assert "LEGISLATION_CORPUS_RIGHTS_CONFIRMED" in result.output + str(result.stderr or "")
    assert not (tmp_path / "dist").exists()


def test_the_guard_that_keeps_source_bytes_out_of_the_site_is_reachable() -> None:
    from billwatcher.pipeline.export import _refuse_source_bytes

    with pytest.raises(StaticExportRefused, match="never the source PDF"):
        _refuse_source_bytes({"index.html": b"%PDF-1.4"})


def test_the_page_admits_an_unstated_licence_rather_than_implying_terms(tmp_path) -> None:
    """A published page that misstates reuse terms is worse than one saying they are pending."""
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    root = tmp_path / "dist"

    build_site(store, site_root=root, prefix="bills.engineers.my", publication_mode="full")

    page = (root / "index.html").read_text(encoding="utf-8")
    assert "Licence: not yet stated" in page
    assert "unlicensed for redistribution" in page
    assert "Licence pending" in page
    assert 'rel="license"' not in page
    # Nothing may imply a grant that was never made.
    assert "CC BY" not in page


def test_a_configured_licence_is_stated_once_the_owner_has_chosen_one(tmp_path) -> None:
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    root = tmp_path / "dist"

    build_site(
        store,
        site_root=root,
        prefix="bills.engineers.my",
        publication_mode="full",
        licence="CC BY 4.0",
        licence_url="https://creativecommons.org/licenses/by/4.0/legalcode",
    )

    page = (root / "index.html").read_text(encoding="utf-8")
    expected = '<link rel="license" href="https://creativecommons.org/licenses/by/4.0/legalcode">'
    assert expected in page
    assert "Open data · CC BY 4.0" in page
    assert "not yet stated" not in page


def test_the_corpus_is_fully_readable_without_scripting(tmp_path) -> None:
    """Progressive enhancement: the rows are in the HTML, so the page works — and is crawlable —
    with JavaScript off. The filter and the theme toggle are hidden until the script runs, so
    nothing on the page is ever inert."""
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-a")
    seed(store, record=bill(16), doc_key="doc-b")
    root = tmp_path / "dist"

    build_site(store, site_root=root, prefix="bills.engineers.my", publication_mode="full")

    page = (root / "index.html").read_text(encoding="utf-8")
    assert page.count("<tr data-search=") == 2
    assert "Rang Undang-Undang Contoh 15" in page
    assert "#filterwrap { position: relative; display: none;" in page
    assert ":root.js #filterwrap { display: block; }" in page
    assert ":root:not(.js) .theme-toggle { display: none; }" in page


def test_the_page_is_self_contained_with_no_third_party_requests(tmp_path) -> None:
    """A published dataset must not break because someone else's CDN went away."""
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    root = tmp_path / "dist"

    build_site(store, site_root=root, prefix="bills.engineers.my", publication_mode="full")

    page = (root / "index.html").read_text(encoding="utf-8")
    assert "http://" not in page
    external = [
        fragment
        for fragment in page.split('"')
        if fragment.startswith("https://") and "bills.engineers.my" not in fragment
    ]
    assert external == []
    assert '<link rel="stylesheet"' not in page
    assert "<script src=" not in page


def test_the_filter_haystack_cannot_break_out_of_its_attribute(tmp_path) -> None:
    store = FileStore(tmp_path / "store")
    record = bill(15)
    record["titles"]["raw_ms"] = 'Rang "quoted" <b>bold</b> & co'
    seed(store, record=record, doc_key="doc-passing")
    root = tmp_path / "dist"

    build_site(store, site_root=root, prefix="bills.engineers.my", publication_mode="full")

    page = (root / "index.html").read_text(encoding="utf-8")
    assert "<b>bold</b>" not in page
    assert "&quot;quoted&quot;" in page  # lower-cased into the data-search attribute, escaped
    row = page.split('<tr data-search="')[1].split('"')[0]
    assert "<" not in row and ">" not in row


def test_the_year_column_comes_from_the_identifier_not_a_guess(tmp_path) -> None:
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    root = tmp_path / "dist"

    build_site(store, site_root=root, prefix="bills.engineers.my", publication_mode="full")

    page = (root / "index.html").read_text(encoding="utf-8")
    assert "<td>2026</td>" in page


def test_each_row_carries_what_the_viewer_needs_to_open_the_record(tmp_path) -> None:
    """The row is the lookup table: opening a record costs one request, for the record itself."""
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    root = tmp_path / "dist"

    build_site(store, site_root=root, prefix="bills.engineers.my", publication_mode="full")

    page = (root / "index.html").read_text(encoding="utf-8")
    assert 'data-route="/akn/my/bill/dr/2026/15/msa@"' in page
    assert 'data-title="Rang Undang-Undang Contoh 15"' in page
    assert 'data-files="akn/my/bill/dr/2026/15/msa@.jsonld akn/my/bill/dr/2026/15/msa@.nq"' in page
    assert '<a class="view-link" href="#/akn/my/bill/dr/2026/15/msa@">' in page
    assert '<div class="record" id="record" hidden></div>' in page


def test_the_route_the_viewer_fetches_is_always_a_file_the_release_published(tmp_path) -> None:
    """The viewer appends `.jsonld` to the route. If that were ever not a published file the
    viewer would 404 on every record, so the invariant is pinned rather than assumed."""
    import re

    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-a")
    seed(store, record=bill(16), doc_key="doc-b")
    root = tmp_path / "dist"

    for representations in ("jsonld", "semantic", "all"):
        build_site(
            store,
            site_root=root,
            prefix="bills.engineers.my",
            publication_mode="full",
            representations=representations,
        )
        page = (root / "index.html").read_text(encoding="utf-8")
        routes = re.findall(r'<tr [^>]*data-route="([^"]+)"', page)
        assert routes, representations
        for route in routes:
            fetched = route.lstrip("/") + ".jsonld"
            assert (root / fetched).exists(), (representations, fetched)


def test_the_identifier_is_still_shown_when_the_viewer_cannot_run(tmp_path) -> None:
    """Without scripting the hash link goes nowhere, so the plain identifier is shown instead and
    the raw format links remain the way in."""
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    root = tmp_path / "dist"

    build_site(store, site_root=root, prefix="bills.engineers.my", publication_mode="full")

    page = (root / "index.html").read_text(encoding="utf-8")
    assert ":root:not(.js) .view-link { display: none; }" in page
    assert ":root.js .no-js-work { display: none; }" in page
    assert '<span class="no-js-work">/akn/my/bill/dr/2026/15</span>' in page
    assert '<a href="/akn/my/bill/dr/2026/15/msa@.jsonld">JSON-LD</a>' in page


def test_every_publishable_representation_has_a_human_label() -> None:
    """A missing label does not fail — both call sites fall back to the raw value, so the page
    renders a whole file path as a link's text. ADR-036 added `md` and this is where that surfaced;
    the invariant is pinned so the next representation cannot repeat it silently.
    """
    from billwatcher.pipeline.export import _MANIFEST_EXTENSIONS
    from billwatcher.pipeline.site import _FORMAT_LABELS

    assert set(_MANIFEST_EXTENSIONS) <= set(_FORMAT_LABELS), (
        f"unlabelled: {sorted(set(_MANIFEST_EXTENSIONS) - set(_FORMAT_LABELS))}"
    )
    assert _FORMAT_LABELS["md"] == "Markdown"
