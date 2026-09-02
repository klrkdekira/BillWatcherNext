"""Validation against the OASIS Akoma Ntoso 3.0 schema, and against the vendored copy of it.

Publishing schema-invalid XML under the name "Akoma Ntoso" defeats the only reason to use the
standard, so validity is checked against the real published XSD rather than asserted by our own
tests agreeing with our own renderer. Two properties therefore need pinning: that `validate_akn`
reports what a consumer's own validator would, and that the vendored schema really is the published
one — which is what the digests in `schemas/README.md` certify, and what these tests re-check
against the files on disk.

The no-network test is the third property. A validation run reaches the network the moment the
`xs:import` for the XML namespace falls back to its absolute W3C URL, and nothing in the output
would say so — it would just be slow, and would fail in a container with no egress.
"""

import re
import socket
from pathlib import Path
from typing import Any

import pytest

from billwatcher.graph import akn_schema
from billwatcher.graph.akn_schema import SCHEMA_PATH, validate_akn
from billwatcher.store import sha256_of

AKN_NS = "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"
SCHEMA_DIR = SCHEMA_PATH.parent
README = SCHEMA_DIR / "README.md"

# `| `file.xsd` | version | source | `sha256` |` — the digest table in README.md.
_DIGEST_ROW = re.compile(r"^\|\s*`([^`]+\.xsd)`\s*\|.*\|\s*`([0-9a-f]{64})`\s*\|\s*$")

VALID = f"""<?xml version="1.0" encoding="utf-8"?>
<akomaNtoso xmlns="{AKN_NS}"><bill name="bill"><meta><identification source="#billwatcher">
<FRBRWork><FRBRthis value="/akn/my/bill/dr/2026/15" /><FRBRuri value="/akn/my/bill/dr/2026/15" />
<FRBRdate date="2026-01-01" name="yearOnly" /><FRBRauthor href="#dewanRakyat" />
<FRBRcountry value="my" /></FRBRWork>
<FRBRExpression><FRBRthis value="/akn/my/bill/dr/2026/15/msa@" />
<FRBRuri value="/akn/my/bill/dr/2026/15" /><FRBRdate date="2026-01-01" name="yearOnly" />
<FRBRauthor href="#dewanRakyat" /><FRBRlanguage language="msa" /></FRBRExpression>
<FRBRManifestation><FRBRthis value="/akn/my/bill/dr/2026/15/msa@.xml" />
<FRBRuri value="/akn/my/bill/dr/2026/15" /><FRBRdate date="2026-01-01" name="yearOnly" />
<FRBRauthor href="#billwatcher" /></FRBRManifestation></identification></meta>
<body><clause eId="cl_1"><num>1</num><content><p>Teks.</p></content></clause></body>
</bill></akomaNtoso>
""".encode()


def recorded_digests() -> dict[str, str]:
    """The digests the README's table certifies, parsed out of the markdown."""
    found: dict[str, str] = {}
    for line in README.read_text(encoding="utf-8").splitlines():
        match = _DIGEST_ROW.match(line)
        if match:
            found[match.group(1)] = match.group(2)
    return found


def test_a_valid_document_reports_no_errors() -> None:
    assert validate_akn(VALID) == []


def test_a_document_with_a_child_the_schema_forbids_names_the_path_to_it() -> None:
    """An error a reviewer can act on has to say *where*, not only that something is wrong."""
    broken = VALID.replace(b"<content><p>Teks.</p></content>", b"<nonsense />")
    errors = validate_akn(broken)
    assert errors
    assert errors[0].startswith("/akomaNtoso/bill/body/clause:")
    assert "nonsense" in errors[0]


def test_a_document_whose_root_is_not_akoma_ntoso_is_rejected() -> None:
    errors = validate_akn(b'<?xml version="1.0"?><notAkn />')
    assert errors == ["/notAkn: 'notAkn' is not an element of the schema"]


def test_a_required_element_left_out_is_reported_rather_than_tolerated() -> None:
    """`meta` is not optional: a document with no FRBR identification is not Akoma Ntoso."""
    errors = validate_akn(
        f'<?xml version="1.0"?><akomaNtoso xmlns="{AKN_NS}"><bill name="bill">'
        f'<body><clause eId="cl_1"><num>1</num><content><p>Teks.</p></content></clause>'
        f"</body></bill></akomaNtoso>".encode()
    )
    assert errors
    assert any("meta" in error for error in errors)


def test_malformed_xml_is_reported_rather_than_raised() -> None:
    """A caller gets a list of errors on every path, so one bad document cannot abort a run."""
    errors = validate_akn(b"<akomaNtoso><bill>")
    assert len(errors) == 1
    assert errors[0].startswith("not parseable as XML:")


def test_undecodable_bytes_are_reported_rather_than_raised() -> None:
    errors = validate_akn(b"\xff\xfe<akomaNtoso/>")
    assert len(errors) == 1
    assert errors[0].startswith("not parseable as XML:")


def test_a_path_shaped_payload_is_not_resolved_as_a_file() -> None:
    """Bytes are validated as a document, never dereferenced as a path or URL.

    xmlschema resolves a short string argument as a filesystem path, so passing raw bytes through
    would let a caller turn this validator into a file reader. Once markdown and Akoma Ntoso can be
    imported, the input is no longer guaranteed to be something we produced.
    """
    for payload in (b"/etc/passwd", b"file:///etc/passwd", b"http://example.org/x.xml", b""):
        errors = validate_akn(payload)
        assert errors and errors[0].startswith("not parseable as XML:"), payload
        assert "passwd" not in errors[0]


def test_the_error_list_is_bounded() -> None:
    """A document wrong in one structural way is usually wrong in it many times over."""
    clause = b'<clause eId="cl_1"><nonsense /></clause>'
    broken = VALID.replace(
        b'<clause eId="cl_1"><num>1</num><content><p>Teks.</p></content></clause>', clause * 40
    )
    assert 0 < len(validate_akn(broken)) <= 10


def test_the_vendored_schema_is_the_published_one_the_readme_certifies() -> None:
    """Byte-for-byte upstream is the property the digests certify; a local edit would break it.

    The relative `schemaLocation="./xml.xsd"` import is deliberately not rewritten, so the two
    files have to stay side by side — which is also why the closure is exactly these two.
    """
    digests = recorded_digests()
    assert sorted(digests) == ["akomantoso30.xsd", "xml.xsd"]
    for name, expected in digests.items():
        path = SCHEMA_DIR / name
        assert path.exists(), f"{name} is recorded in README.md but not vendored"
        assert sha256_of(path.read_bytes()) == expected
    assert SCHEMA_PATH.name == "akomantoso30.xsd"
    assert sorted(p.name for p in SCHEMA_DIR.glob("*.xsd")) == ["akomantoso30.xsd", "xml.xsd"]


def test_the_transitive_closure_of_the_schema_is_those_two_files_and_nothing_else() -> None:
    """The reason validation never reaches the network, stated as a check rather than a comment."""
    akomantoso = (SCHEMA_DIR / "akomantoso30.xsd").read_text(encoding="utf-8")
    assert "xsd:include" not in akomantoso
    assert akomantoso.count("xsd:import") == 1
    assert 'schemaLocation="./xml.xsd"' in akomantoso
    xml_xsd = (SCHEMA_DIR / "xml.xsd").read_text(encoding="utf-8")
    assert "xs:import" not in xml_xsd and "xsd:import" not in xml_xsd


def test_validation_works_with_no_network_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Built from the vendored files by path, in a validation run and in a container with no egress.

    The cache is cleared first so the schema is *built* under these conditions, not merely used —
    building is when the `xs:import` would resolve, and a warm cache would hide a fallback to the
    absolute W3C URL.
    """

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise OSError("this test runs with no network")

    akn_schema._schema.cache_clear()
    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    assert validate_akn(VALID) == []
    assert validate_akn(b"<akomaNtoso><bill>")[0].startswith("not parseable as XML:")


def test_the_schema_is_built_once_and_reused() -> None:
    """Building the object from a 239 KB XSD is not free; over a corpus it has to amortise."""
    assert akn_schema._schema() is akn_schema._schema()
    assert isinstance(SCHEMA_PATH, Path)
