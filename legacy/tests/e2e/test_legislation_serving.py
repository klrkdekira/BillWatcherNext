"""Serving the file-first legislation corpus on truncatable FRBR paths (ADR-018).

The corpus is seeded through the real pipeline steps rather than by writing artifacts by hand:
`save_bill` -> `save_document` -> `save_markdown` plus the markdown provenance record that declares
the language -> `convert_to_akn` -> `generate_semantic_files`. A hand-written `document.akn.xml`
would let these tests pass over a corpus the pipeline could never produce, which is the one thing a
serving test must not do.

The load-bearing assertion is the redaction one. Publication is gated (`SERVE_LEGISLATION_CORPUS`)
and, when it is open, the default mode publishes structure only — so no sentence of the source
document's body may appear in *any* response, while the provision numbers and headings, which
ADR-004 permits as bounded published fragments, must.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from billwatcher.pipeline.akn import RegexMarkdownStructureExtractor, convert_to_akn
from billwatcher.pipeline.akn_schema import validate_akn
from billwatcher.pipeline.documents import doc_key
from billwatcher.pipeline.provenance import build_record
from billwatcher.pipeline.semantic import generate_semantic_files
from billwatcher.pipeline.store import FileStore, sha256_of
from billwatcher.web.corpus import Alternate, alternates, canonical_url, link_header
from billwatcher.web.security_headers import SECURITY_HEADERS
from tests.e2e.test_web import client

BASE = "http://testserver"
OFFICIAL = "https://www.parlimen.gov.my/files/billindex/pdf/2026/DR/RUU15.pdf"
OFFICIAL_EN = "https://www.parlimen.gov.my/files/billindex/pdf/2026/DR/RUU15-BI.pdf"
PDF = b"%PDF-1.7\nthe source document\n%%EOF"
PDF_EN = b"%PDF-1.7\nthe English source document\n%%EOF"
SLUG = "dr-15-2026"
DOC_KEY = doc_key(OFFICIAL)

WORK = "/akn/my/bill/dr/2026/15"
EXPRESSION = f"{WORK}/msa@"

# A plausible Malay bill: one Part, three clauses, a mix of clause-level and subsection-level text.
# No Arrangement of Clauses heading, so the language cannot be sniffed out of the document and has
# to come from the markdown provenance record — which is how a real import declares it.
MARKDOWN = """\
Bahagian I — PERMULAAN

1. Tajuk ringkas dan permulaan kuat kuasa

(1) Akta ini bolehlah dinamakan Akta Perlindungan Saksi 2026.

(2) Akta ini mula berkuat kuasa pada tarikh yang ditetapkan oleh Menteri melalui pemberitahuan
dalam Warta.

2. Tafsiran

Dalam Akta ini, saksi bermaksud seseorang yang memberikan keterangan kepada pihak berkuasa.

3. Kewajipan untuk melaporkan

(1) Seseorang pegawai awam hendaklah melaporkan apa-apa perbuatan salah kepada pihak berkuasa.

(2) Kegagalan mematuhi subseksyen (1) merupakan suatu kesalahan di bawah Akta ini.
"""

MARKDOWN_EN = """\
Part I — PRELIMINARY

1. Short title and commencement

(1) This Act may be cited as the Witness Protection Act 2026.

2. Interpretation

In this Act, a witness means a person who gives evidence to an authority.
"""

# Sentences of the source document's own body. None of these may appear in any published bytes
# while the publication mode is `metadata`.
BODY_SENTENCES = (
    "Akta ini bolehlah dinamakan",
    "mula berkuat kuasa pada tarikh yang ditetapkan",
    "saksi bermaksud seseorang yang memberikan keterangan",
    "Seseorang pegawai awam hendaklah melaporkan",
    "Kegagalan mematuhi subseksyen",
)

# Structure, which is what `metadata` mode exists to publish.
HEADINGS = (
    "PERMULAAN",
    "Tajuk ringkas dan permulaan kuat kuasa",
    "Tafsiran",
    "Kewajipan untuk melaporkan",
)

BILL = {
    "identifier": {
        "raw": "D.R.15/2026",
        "normalized": "DR-15-2026",
        "number": 15,
        "year": 2026,
        "originating_chamber": "dewan_rakyat",
        "slug": SLUG,
    },
    "titles": {"raw_ms": "Rang Undang-undang Perlindungan Saksi 2026"},
    "chambers": {
        "dewan_rakyat": {
            "status_raw": "Bacaan Pertama",
            "status_normalized": "first_reading",
            "dates": {"first_reading": [{"start": "2026-03-10", "end": None}]},
            "source_url": "https://www.parlimen.gov.my/bills-dewan-rakyat.html",
        }
    },
    "documents": [{"url": OFFICIAL, "chamber": "dewan_rakyat"}],
}

LEVELS = (
    "/akn/my",
    "/akn/my/bill",
    "/akn/my/bill/dr",
    "/akn/my/bill/dr/2026",
    WORK,
    EXPRESSION,
    f"{EXPRESSION}/~part_I__cl_3",
)

HTML_PAGES = (WORK, EXPRESSION, f"{EXPRESSION}/~part_I__cl_3")
MACHINE_VARIANTS = {
    f"{EXPRESSION}.xml": "application/akn+xml",
    f"{EXPRESSION}.jsonld": "application/ld+json",
    f"{EXPRESSION}.nq": "application/n-quads",
}


def seed(
    root: Path, *, url: str = OFFICIAL, markdown: str = MARKDOWN, language: str = "ms"
) -> None:
    """Build the corpus the way the pipeline builds it, one real step at a time.

    Called twice for the two-language case; the second call converts only the new document, because
    the first one's provenance still matches what this code would produce from it.
    """
    store = FileStore(root)
    store.save_bill(SLUG, BILL)
    content = PDF if language == "ms" else PDF_EN
    keys = {"bill_slug": SLUG, "doc_key": doc_key(url), "version": 1}
    store.save_document(
        **keys,
        content=content,
        metadata={
            "source_url": url,
            "final_url": url,
            "retrieved_at": "2026-08-17T00:00:00+00:00",
            "sha256": sha256_of(content),
            "byte_size": len(content),
            "bill_slug": SLUG,
            "chamber": "dewan_rakyat",
        },
    )
    store.save_markdown(**keys, content=markdown)
    store.save_provenance(
        **keys,
        artifact="markdown",
        record=build_record(
            artifact="markdown",
            inputs={
                "source_files": [{"file": "document.pdf", "sha256": sha256_of(content)}],
                # The language is declared at import, not sniffed: it becomes a permanent part of
                # the Expression IRI, and this markdown carries no Arrangement heading to read it
                # from.
                "language": language,
                "producer": "operator-import",
            },
            outputs={"document.md": markdown.encode()},
        ),
    )
    converted = convert_to_akn(store, extractor=RegexMarkdownStructureExtractor())
    assert converted.counts["converted"] == 1, converted.as_payload()
    semantic = generate_semantic_files(store, base_iri=BASE)
    assert semantic.counts["converted"] == 1, semantic.as_payload()


def version_dir(root: Path) -> Path:
    return root / "documents" / SLUG / DOC_KEY / "v001"


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    seed(tmp_path)
    return tmp_path


def serving(root: Path, **overrides: object) -> TestClient:
    return client(
        pipeline_data_root=root,
        serve_legislation_corpus=True,
        public_base_url=BASE,
        **overrides,
    )


def test_every_truncation_of_a_citation_resolves(corpus: Path) -> None:
    """ADR-018's one hard requirement: no level of a published path is a dead end."""
    with serving(corpus) as browser:
        for path in LEVELS:
            page = browser.get(path)
            assert page.status_code == 200, path
            assert page.headers["content-type"].startswith("text/html"), path
        assert "Dewan Rakyat" in browser.get("/akn/my/bill").text
        assert "2026" in browser.get("/akn/my/bill/dr").text
        assert "Bill 15 of 2026" in browser.get("/akn/my/bill/dr/2026").text
        assert "D.R.15/2026" in browser.get(WORK).text
        assert EXPRESSION in browser.get(WORK).text


def test_each_extension_variant_is_served_with_its_own_media_type(corpus: Path) -> None:
    with serving(corpus) as browser:
        for path, media_type in MACHINE_VARIANTS.items():
            response = browser.get(path)
            assert response.status_code == 200, path
            assert response.headers["content-type"].startswith(media_type), path

        xml = browser.get(f"{EXPRESSION}.xml").content
        # Redaction must not cost schema validity: an invalid Akoma Ntoso document is not a useful
        # thing to publish either.
        assert validate_akn(xml) == []
        assert b'<FRBRthis value="/akn/my/bill/dr/2026/15/msa@.xml"' in xml

        graph = json.loads(browser.get(f"{EXPRESSION}.jsonld").text)
        subjects = {entry["@id"] for entry in graph["@graph"]}
        assert f"{BASE}{EXPRESSION}" in subjects
        assert f"{BASE}{EXPRESSION}/~part_I__cl_3" in subjects

        quads = browser.get(f"{EXPRESSION}.nq").text.splitlines()
        assert quads and all(line.endswith(" .") for line in quads)
        assert any(f"<{BASE}{EXPRESSION}/~part_I__cl_3>" in line for line in quads)


def test_metadata_mode_publishes_structure_and_withholds_every_body_sentence(
    corpus: Path,
) -> None:
    """The default mode. Structure and identifiers are published; the drafted words are not."""
    with serving(corpus) as browser:
        bodies = {path: browser.get(path).text for path in LEVELS}
        bodies.update({path: browser.get(path).text for path in MACHINE_VARIANTS})
        for path, body in bodies.items():
            for sentence in BODY_SENTENCES:
                assert sentence not in body, f"{path} published {sentence!r}"

        page = bodies[EXPRESSION]
        for heading in HEADINGS:
            assert heading in page, heading
        # Numbering, in the document's own language.
        assert "Bahagian I" in page
        assert "Fasal 3" in page
        assert "Subseksyen 2" in page
        # And the same structure survives into the machine representations.
        assert "Kewajipan untuk melaporkan" in bodies[f"{EXPRESSION}.xml"]
        assert "Kewajipan untuk melaporkan" in bodies[f"{EXPRESSION}.jsonld"]
        assert "<num>3</num>" in bodies[f"{EXPRESSION}.xml"]
        # The withholding is stated on the page rather than left to be inferred.
        assert "Structure only" in page
        assert "not republished here" in page


def test_full_mode_publishes_the_text_once_that_decision_is_recorded(corpus: Path) -> None:
    """The rights decision is a configuration change over a corpus that already holds the text."""
    with serving(corpus, legislation_publication_mode="full") as browser:
        page = browser.get(EXPRESSION).text
        xml = browser.get(f"{EXPRESSION}.xml").text
        quads = browser.get(f"{EXPRESSION}.nq").text
        for sentence in ("Seseorang pegawai awam hendaklah melaporkan", "Akta ini bolehlah"):
            assert sentence in page, sentence
            assert sentence in xml, sentence
            assert sentence in quads, sentence
        assert "Structure only" not in page


def test_the_link_header_carries_every_sibling_and_the_official_document(corpus: Path) -> None:
    with serving(corpus) as browser:
        for path in (EXPRESSION, *MACHINE_VARIANTS):
            link = browser.get(path).headers["link"]
            assert link.count('rel="alternate"') == 3, path
            assert f'<{OFFICIAL}>; rel="canonical"' in link, path
            # The representation being served is not advertised as an alternate of itself.
            assert f"<{path}>" not in link, path

        html_link = browser.get(EXPRESSION).headers["link"]
        assert f'<{EXPRESSION}.xml>; rel="alternate"; type="application/akn+xml"' in html_link
        assert f'<{EXPRESSION}.nq>; rel="alternate"; type="application/n-quads"' in html_link

        head = browser.get(EXPRESSION).text.split("</head>", 1)[0]
        for extension, media_type in (
            ("xml", "application/akn+xml"),
            ("jsonld", "application/ld+json"),
            ("nq", "application/n-quads"),
        ):
            assert (
                f'<link rel="alternate" type="{media_type}" href="{EXPRESSION}.{extension}">'
                in head
            ), extension


def test_the_link_helpers_are_pure_and_refuse_a_poisoned_url() -> None:
    from billwatcher.pipeline.frbr import WorkIdentity

    identity = WorkIdentity(doc_type="bill", chamber_code="dr", year=2026, number=15)
    siblings = alternates(identity, "ms", current="xml")
    assert siblings == (
        Alternate(EXPRESSION, "text/html"),
        Alternate(f"{EXPRESSION}.jsonld", "application/ld+json"),
        Alternate(f"{EXPRESSION}.nq", "application/n-quads"),
    )
    assert link_header(siblings, canonical=None).count(", ") == 2
    assert link_header((), canonical=OFFICIAL) == f'<{OFFICIAL}>; rel="canonical"'

    assert canonical_url({"source_url": OFFICIAL}) == OFFICIAL
    # A sidecar URL is upstream-derived text, so anything that could forge a second header value or
    # a second link is refused rather than emitted.
    for poisoned in (
        "https://x.example/a\r\nX-Evil: 1",
        # Python's `$` also matches just before a trailing newline, so the guard whose whole job is
        # to reject anything that could forge a header was letting this one into one.
        "https://x.example/a\n",
        "https://x.example/a\r\n",
        "\nhttps://x.example/a",
        "https://x.example/a>, <https://evil.example/b",
        "javascript:alert(1)",
        "",
    ):
        assert canonical_url({"source_url": poisoned}) is None, poisoned
    assert canonical_url({}) is None


def test_robots_and_caching_differ_by_representation(corpus: Path) -> None:
    with serving(corpus) as browser:
        for path in HTML_PAGES:
            response = browser.get(path)
            # Our own derived pages are the thing ADR-018 wants indexed.
            assert "x-robots-tag" not in {key.lower() for key in response.headers}, path
        for path in MACHINE_VARIANTS:
            assert browser.get(path).headers["x-robots-tag"] == "noindex", path
        for path in (EXPRESSION, f"{EXPRESSION}.xml"):
            # Derived files regenerate when their source or the renderer changes, so they must not
            # be cached the way the immutable archived bytes are.
            assert browser.get(path).headers["cache-control"] == "public, max-age=300", path
            assert "immutable" not in browser.get(path).headers["cache-control"], path


def test_the_etag_covers_the_bytes_actually_returned(corpus: Path) -> None:
    with serving(corpus) as browser:
        for path in (EXPRESSION, *MACHINE_VARIANTS):
            first = browser.get(path)
            etag = first.headers["etag"]
            assert etag == f'"{sha256_of(first.content)}"', path
            again = browser.get(path, headers={"If-None-Match": etag})
            assert again.status_code == 304, path
            assert not again.content, path

        # And the ETag is over the *redacted* bytes, not over the stored file.
        stored = (version_dir(corpus) / "document.akn.xml").read_bytes()
        assert browser.get(f"{EXPRESSION}.xml").headers["etag"] != f'"{sha256_of(stored)}"'


def test_the_corpus_is_withheld_by_default_and_says_why(corpus: Path) -> None:
    """The gate is closed until the rights review concludes and is recorded (ADR-018)."""
    with client(pipeline_data_root=corpus) as browser:
        for path in (*LEVELS, *MACHINE_VARIANTS):
            response = browser.get(path)
            assert response.status_code == 404, path
            assert "rights review has concluded" in response.text, path
        # The rest of the site is unaffected.
        assert browser.get("/bills").status_code == 200
        assert browser.get(f"/bills/{SLUG}").status_code == 200


def test_a_work_we_hold_no_reading_of_is_a_plain_404(corpus: Path) -> None:
    with serving(corpus) as browser:
        absent = browser.get("/akn/my/bill/dr/2026/99")
        assert absent.status_code == 404
        assert "no reading of that document" in absent.text
        assert browser.get("/akn/my/bill/dr/2026/99/msa@").status_code == 404
        # A language we hold no Expression in, and a provision that does not exist.
        assert browser.get(f"{WORK}/eng@").status_code == 404
        unknown = browser.get(f"{EXPRESSION}/~cl_99")
        assert unknown.status_code == 404
        assert "no provision with that identifier" in unknown.text
        # An Act path over a corpus that holds a bill reading resolves to nothing.
        assert browser.get("/akn/my/act/dr/2026/15").status_code == 404


def test_no_request_string_can_address_a_file_we_did_not_write(corpus: Path) -> None:
    """HANDOFF 17: every segment is validated before the store is touched."""
    attacks = (
        "/akn/my/bill/dr/2026/15/..%2f..%2f..%2fetc%2fpasswd",
        "/akn/my/bill/dr/2026/15%2f..%2f..%2fetc%2fpasswd/msa@",
        "/akn/my/bill/dr/2026/15/msa@.xml/~..%2f..%2fetc%2fpasswd",
        "/akn/my/bill/dr/2026/15/msa@/~%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        "/akn/my/bill/dr/2026/15/msa@/../../../../../../etc/passwd",
        "/akn/my/bill/dr/2026/015/msa@",
        "/akn/my/bill/dr/26/15/msa@",
        "/akn/my/bill/xx/2026/15/msa@",
        "/akn/my/parliament/dr/2026/15/msa@",
        "/akn/my/bill/dr/2026/15/zzz@",
        "/akn/my/bill/dr/2026/15/msa@.exe",
        "/akn/my/bill/dr/2026/15/msa",
        "/akn/my/bill/dr/2026/15/msa@/part_I",
        "/akn/my/bill/dr/2026/15/msa@.xml/~part_I__cl_3",
    )
    with serving(corpus) as browser:
        for attack in attacks:
            response = browser.get(attack)
            assert response.status_code in {400, 404}, f"{attack} -> {response.status_code}"
            assert b"root:" not in response.content, attack


def test_an_unreadable_artifact_is_a_503_rather_than_a_missing_document(corpus: Path) -> None:
    """A published corpus with a hole in it is our problem, and reports as one."""
    (version_dir(corpus) / "document.nq").unlink()
    with serving(corpus) as browser:
        for path in (f"{EXPRESSION}.nq", f"{EXPRESSION}.jsonld"):
            response = browser.get(path)
            # The JSON-LD is redacted from the N-Quads so that one redaction produces both; with
            # the N-Quads gone there is nothing to publish a redacted JSON-LD from.
            assert response.status_code == 503, path
            assert "unavailable" in response.text
        # Everything derived from the Akoma Ntoso still serves.
        assert browser.get(f"{EXPRESSION}.xml").status_code == 200
        assert browser.get(EXPRESSION).status_code == 200


def test_every_page_names_its_source_document_and_the_gate_verdict(corpus: Path) -> None:
    """A reader is entitled to know this is a machine reading and how well it accounted for the
    source, on the page rather than in an operator's manifest."""
    with serving(corpus) as browser:
        for path in HTML_PAGES:
            page = browser.get(path).text
            assert "Unofficial index" in page, path
            assert "Machine-derived" in page, path
            assert "LLM-assisted" in page, path
            assert OFFICIAL in page, path
            assert sha256_of(PDF) in page, path
            assert "Fidelity gate P1: passed" in page, path
            assert "distinct words in the transcription" in page, path
            # Never in-force or current-law language (HANDOFF 14), and never the Gazette notice.
            assert "currently in force" not in page.replace(
                "not a statement that it is enacted or currently in force", ""
            ), path
            assert "Gazette" not in page and "Warta" not in page, path
        # The regex reader is named as such rather than passed off as a language model.
        assert "deterministic pattern reader" in browser.get(EXPRESSION).text


def test_the_corpus_pages_need_no_script_and_carry_no_datastar(corpus: Path) -> None:
    """These pages are static documents; ADR-012 grants Datastar to two interactions, not to all.

    Asserted here rather than by extending the hardcoded path list in
    `test_progressive_enhancement.py`: those pages are always served, and these only exist while
    the publication gate is open.
    """
    with serving(corpus) as browser:
        for path in LEVELS:
            page = browser.get(path).text
            assert "<script>" not in page, path
            body = page.split("</head>", 1)[-1]
            assert "<script" not in body, path
            for attribute in ("data-signals", "data-on:", "data-bind", "data-init", "data-show"):
                assert attribute not in page, f"{path} carries {attribute}"


def test_the_two_language_readings_are_two_expressions_of_one_work(tmp_path: Path) -> None:
    """The property `frbr` exists for: one Work, one identifier, two resolvable languages."""
    seed(tmp_path)
    seed(tmp_path, url=OFFICIAL_EN, markdown=MARKDOWN_EN, language="en")
    with serving(tmp_path) as browser:
        work = browser.get(WORK).text
        assert EXPRESSION in work
        assert f"{WORK}/eng@" in work
        assert "English, Malay" in browser.get("/akn/my/bill/dr/2026").text

        english = browser.get(f"{WORK}/eng@")
        assert english.status_code == 200
        assert "Short title and commencement" in english.text
        # Each provision is named in its own Expression's language.
        assert "Clause 1" in english.text and "Part I" in english.text
        assert 'lang="en"' in english.text
        # Only the Malay title is on the record, and it is tagged as Malay even here.
        assert 'lang="ms">Rang Undang-undang Perlindungan Saksi 2026</span>' in english.text
        assert "Tajuk ringkas" not in english.text
        assert "This Act may be cited" not in english.text
        # The Malay Expression is untouched by the second reading.
        malay = browser.get(EXPRESSION).text
        assert "Fasal 1" in malay and "Short title" not in malay
        assert f"<{WORK}/eng@.xml>" not in browser.get(f"{EXPRESSION}.xml").headers["link"]


def test_a_work_page_with_two_readings_attributes_each_document_to_its_own_expression(
    tmp_path: Path,
) -> None:
    """Two readings mean two source PDFs, two digests and two gate verdicts.

    Printing the first Expression's as the Work's attributed one PDF's provenance — its URL, its
    sha256, the verdict on its reading — to the other language's reading, which is a false statement
    about the very thing these pages exist to be honest about. The Work-level block is omitted
    instead and each Expression carries its own; a Work with a single reading still gets it, because
    there is nothing to confuse (`test_every_page_names_its_source_document_and_the_gate_verdict`).
    """
    seed(tmp_path)
    seed(tmp_path, url=OFFICIAL_EN, markdown=MARKDOWN_EN, language="en")
    with serving(tmp_path) as browser:
        work = browser.get(WORK).text

        # No Work-level provenance block at all: it could only ever have named one of the two.
        assert "Source document." not in work
        assert "Fidelity gate P1:" not in work
        assert sha256_of(PDF) not in work and sha256_of(PDF_EN) not in work

        # Each Expression names the document its own reading came from, and its own verdict.
        english, _, malay = work.partition(f'<a href="{EXPRESSION}">Malay</a>')
        assert OFFICIAL_EN in english and OFFICIAL not in english
        assert OFFICIAL in malay and OFFICIAL_EN not in malay
        assert english.count("fidelity gate P1 <strong>passed</strong>") == 1
        assert malay.count("fidelity gate P1 <strong>passed</strong>") == 1


def test_the_corpus_pages_carry_the_site_security_headers(corpus: Path) -> None:
    """The policy is a property of the application, so a new surface does not get to skip it."""
    with serving(corpus) as browser:
        for path in (EXPRESSION, f"{EXPRESSION}.xml"):
            headers = browser.get(path).headers
            for header, value in SECURITY_HEADERS.items():
                assert headers[header] == value, f"{path} is missing {header}"


def test_an_enabled_but_empty_corpus_resolves_instead_of_failing(tmp_path: Path) -> None:
    """Turning the flag on before the pipeline has run is a real state, and must not 500."""
    with serving(tmp_path / "never-written") as browser:
        for path in ("/akn/my", "/akn/my/bill", "/akn/my/bill/dr", "/akn/my/bill/dr/2026"):
            page = browser.get(path)
            assert page.status_code == 200, path
        assert "We hold no reading at this level yet" in browser.get("/akn/my/bill/dr").text
        assert browser.get(WORK).status_code == 404
        assert browser.get(f"{EXPRESSION}.xml").status_code == 404
