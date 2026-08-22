"""Validation against the OASIS Akoma Ntoso 3.0 schema.

Publishing schema-invalid XML under the name "Akoma Ntoso" defeats the only reason to use the
standard: a consumer's off-the-shelf AKN tooling has to be able to read it. So validity is checked
against the real published XSD rather than asserted by our own tests agreeing with our own
renderer.

The schema is vendored (`schemas/akomantoso30.xsd` plus the one `xml.xsd` it imports) and loaded
from disk by path, never by URL — there is no network dependency in a validation run, and none in a
test run either. Building the schema object from a 239 KB XSD is not free, so it is built once and
cached; over a corpus of a couple of thousand documents that cost amortises to nothing.

The library choice lives behind `validate_akn` alone. `xmlschema` was preferred over `lxml` because
it is pure Python with no native code to audit, ships `py.typed` so strict mypy needs no escape
hatch, and this project has no CI — every native dependency is one more thing a manual review is
the only control on (the same reasoning ADR-016 used to reject pdfplumber). If profiling ever
argues for libxml2's speed, the swap happens inside this one function.
"""

from functools import cache
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

import xmlschema

SCHEMA_PATH = Path(__file__).parent / "schemas" / "akomantoso30.xsd"

# How many schema errors a caller is shown. A document that is wrong in one structural way is
# usually wrong in it many times over; the first handful identify the defect, and the rest are the
# same sentence again.
_ERROR_LIMIT = 10


@cache
def _schema() -> xmlschema.XMLSchema:
    return xmlschema.XMLSchema(SCHEMA_PATH)


def validate_akn(xml_bytes: bytes) -> list[str]:
    """Schema errors in an Akoma Ntoso document, most structural first; empty when it is valid."""
    # Wrapped in a stream, for two reasons. Given a short *string*, xmlschema tries to resolve it as
    # a path or URL, so bytes like b"/etc/passwd" would reach the filesystem — and while the input
    # is our own render today, markdown and AKN can now be imported and this function is reachable
    # from a serving path, so the source is not something to assume. Passing bytes also lets the
    # parser honour the document's own encoding declaration instead of us presuming UTF-8.
    try:
        errors = list(_schema().iter_errors(BytesIO(xml_bytes)))
    except (xmlschema.XMLSchemaException, ElementTree.ParseError) as error:
        return [f"not parseable as XML: {error}"]
    return [_describe(error) for error in errors[:_ERROR_LIMIT]]


def _describe(error: xmlschema.XMLSchemaValidationError) -> str:
    path = getattr(error, "path", None) or "<document>"
    reason = (error.reason or "").strip().splitlines()
    return f"{path}: {reason[0] if reason else 'invalid'}"
