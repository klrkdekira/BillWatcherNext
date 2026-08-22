"""Layout-aware reading of a legislative PDF (HANDOFF 26.1).

Naive text extraction loses the structure Malaysian legislative typography carries in position:
section numbers hang at the left margin, marginal notes sit in the right margin *on the same
baseline as the text they annotate*, running heads and page numbers repeat, and schedules
restart numbering. `billwatcher.scraper.parse_document` deliberately produces flat page text for
search and keeps doing so; this module produces the second, geometric reading that the structure
parser and Gate L1 need.

It reads with `pdfminer.six`, which returns each typeset line's bounding box together with its
already-decoded Unicode text, its font, and its size. `pypdf`, which this project already
depends on, cannot serve: its `visitor_text` callback reports the *line's* starting x rather than
each run's, so a marginal note is spliced into the middle of the provision it annotates, and its
lower-level operand visitor reports accurate matrices but undecoded, font-encoded bytes. Both
were measured before the dependency was added (ADR-016).

Coordinates are PDF user space: the origin is the bottom-left of the page, so a *larger* `y` is
*higher* on the page. Every threshold below is a fraction of the page box rather than a count of
points, because Malaysian legislation is published on more than one paper size.
"""

import io
import re
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTChar, LTPage, LTTextContainer, LTTextLine

from billwatcher.scraper.normalize import normalize_text
from billwatcher.version import LAYOUT_EXTRACTOR_VERSION

# A bound on work done for one document. The corpus's largest bill is well under this; a PDF
# claiming more pages is refused rather than allowed to occupy a worker indefinitely.
MAX_PAGES = 2000

# Bands measured from the top and bottom of the page in which a *repeated* line is running
# furniture rather than content.
_HEADER_BAND = 0.92
_FOOTER_BAND = 0.08

# A line is furniture only if it repeats near the same edge on at least this fraction of pages.
# One page's stray line is not a running head.
_REPEAT_FRACTION = 0.6

# Known limit: a plain BODY paragraph — not a Part/Chapter/Schedule heading, not a numbered
# provision, not a marginal note — that happens to sit above the header threshold or below the
# footer one, on a page whose preceding content ran short, is not protected the way those three
# are. If such a line also masks to the same digit-free key and repeats at a shared baseline
# across most pages, it can still be discarded as furniture. Every structural signal Gate L1's
# comparison depends on (headings and provision numbers) is protected; only a stray sentence of
# free body text is at residual risk, and only under a specific and unusual confluence of
# conditions real typesetting rarely produces — a body paragraph starting within the top or
# bottom ~8% of a page. Widening the protection further risks the opposite failure: a genuine
# running head that happens to resemble body text would stop being recognised as furniture at all.

# ...and only if those repetitions sit at the same height, as a fraction of the page. A
# running head has a fixed baseline; a heading that happens to recur near the top does not.
_BASELINE_TOLERANCE = 0.01

# A line starting this far right of the body margin, as a fraction of page width, is in the
# margin column rather than the text column.
_MARGIN_OFFSET = 0.45

# A marginal note is short. A long line starting right of the column is an indented block.
_MARGIN_MAX_CHARS = 80

# A heading is set larger than the body. Below this ratio the difference is font rounding.
_HEADING_SIZE_RATIO = 1.08

_PAGE_NUMBER_RE = re.compile(r"^\W*(?:\d{1,4}|[ivxlcdm]{1,7})\W*$", re.IGNORECASE)

ROLES = frozenset({"body", "heading", "provision", "marginal", "header", "footer", "page_number"})

EXTRACTOR_NAME = "pdfminer-layout"


@dataclass(frozen=True, slots=True)
class Line:
    """One typeset line, with the geometry that decides what it is."""

    page: int
    x0: float
    y: float
    size: float
    font: str | None
    text: str
    role: str

    @property
    def is_content(self) -> bool:
        """Whether this line carries document text rather than page furniture."""
        return self.role in {"body", "heading", "provision", "marginal"}


@dataclass(frozen=True, slots=True)
class PageBox:
    number: int
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class LayoutDocument:
    """The geometric reading of one document version."""

    extractor_name: str
    extractor_version: str
    status: str
    lines: tuple[Line, ...] = ()
    pages: tuple[PageBox, ...] = ()
    duration_ms: int = 0
    error: str | None = None
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def content_lines(self) -> tuple[Line, ...]:
        """Content in reading order, with running heads, feet, and page numbers removed.

        Furniture is dropped only *after* every line has recorded the page it came from, so
        pinpoint citation back into the stored PDF survives (HANDOFF 26.1).
        """
        return tuple(line for line in self.lines if line.is_content)


def extract_layout(content: bytes, *, max_pages: int = MAX_PAGES) -> LayoutDocument:
    """Read a PDF into classified, geometry-bearing lines.

    Pure: it neither fetches nor mutates anything, and takes the stored bytes as its only input
    so that a re-read at a newer extractor version is a replay rather than a re-crawl.
    """
    started = time.monotonic()
    if not content.startswith(b"%PDF-"):
        return _failed(started, "input does not have PDF magic bytes")
    try:
        pages: list[PageBox] = []
        raw: list[Line] = []
        for number, page in enumerate(
            extract_pages(io.BytesIO(content), laparams=LAParams(), maxpages=max_pages), start=1
        ):
            pages.append(_page_box(page, number))
            raw.extend(_page_lines(page, number))
    except Exception as error:  # pdfminer raises several parser-specific types
        return _failed(started, f"{type(error).__name__}: {error}")

    if not pages:
        return _failed(started, "PDF contains no pages")
    lines = _classify(raw, pages)
    status = "succeeded" if any(line.is_content for line in lines) else "empty"
    return LayoutDocument(
        extractor_name=EXTRACTOR_NAME,
        extractor_version=LAYOUT_EXTRACTOR_VERSION,
        status=status,
        lines=lines,
        pages=tuple(pages),
        duration_ms=round((time.monotonic() - started) * 1000),
        counts=dict(Counter(line.role for line in lines)),
    )


def _page_box(page: LTPage, number: int) -> PageBox:
    _, _, x1, y1 = page.bbox
    return PageBox(number, float(x1) or 1.0, float(y1) or 1.0)


def _page_lines(page: LTPage, number: int) -> list[Line]:
    """Every text line on one page, in top-to-bottom then left-to-right order.

    pdfminer already separates the margin column into its own line, because a marginal note is
    horizontally distant from the text it sits beside. Ordering is imposed here rather than
    trusted, since a two-column baseline must read left before right.
    """
    lines: list[Line] = []
    for element in page:
        if not isinstance(element, LTTextContainer):
            continue
        for item in element:
            if not isinstance(item, LTTextLine):
                continue
            text = normalize_text(item.get_text())
            if not text:
                continue
            glyphs = [glyph for glyph in item if isinstance(glyph, LTChar)]
            lines.append(
                Line(
                    page=number,
                    x0=float(item.x0),
                    y=float(item.y0),
                    # The modal glyph size, so one superscript does not demote a heading.
                    size=_modal(round(float(glyph.size), 1) for glyph in glyphs),
                    font=str(glyphs[0].fontname) if glyphs else None,
                    text=text,
                    role="body",
                )
            )
    lines.sort(key=lambda line: (-line.y, line.x0))
    return lines


def _is_structural_heading(text: str) -> bool:
    """Whether a line is recognisable as a Part/Chapter/Schedule heading regardless of position."""
    from billwatcher.legislation.vocabulary import container_heading, schedule_heading

    return container_heading(text) is not None or schedule_heading(text) is not None


def _classify(lines: list[Line], pages: list[PageBox]) -> tuple[Line, ...]:
    """Assign each line a role from its geometry and from what repeats across pages."""
    if not lines:
        return ()
    boxes = {page.number: page for page in pages}
    # Weighted by how much text sits at each size and margin, not by how many lines do. Counting
    # lines lets a page of short marginal notes outvote the body column that holds the document.
    body_size = _weighted_modal((round(line.size, 1), len(line.text)) for line in lines)
    body_margin = _weighted_modal((round(line.x0), len(line.text)) for line in lines)
    furniture = _repeated_furniture(lines, boxes, page_count=len(pages))

    classified: list[Line] = []
    for line in lines:
        box = boxes.get(line.page)
        height = box.height if box else 1.0
        width = box.width if box else 1.0
        relative_y = line.y / height if height else 0.0
        in_header = relative_y >= _HEADER_BAND
        in_footer = relative_y <= _FOOTER_BAND

        if (in_header or in_footer) and _PAGE_NUMBER_RE.match(line.text):
            role = "page_number"
        elif _is_structural_heading(line.text):
            # A Part, Chapter, or Schedule heading is checked *before* the furniture test,
            # deliberately. A document that opens each Part on a fresh page can place its heading
            # near the top of most pages, at a consistent baseline — which is exactly what a
            # running head also looks like. Digit-masking alone cannot tell "BAHAGIAN 1" on page 1
            # apart from "BAHAGIAN 2" on page 8 from "Akta 710   12" and "Akta 710   13": both
            # collapse to the same masked key and repeat near a fixed baseline. Recognising the
            # line as structure first is what stops real Parts from being erased as furniture.
            role = "heading"
        elif _hangs_left(line, body_margin):
            # Checked before both the furniture test and the heading test, deliberately, and for
            # the same reason as the structural heading above: a numbered provision can land in
            # the header or footer band exactly as easily as a Part heading can — a short Act, or
            # a page whose preceding text runs long, can leave a section's own opening line
            # sitting above the header threshold. `Seksyen 1.` on one page and `Seksyen 2.` on the
            # next mask to the same digit-free key and repeat at a shared baseline, which is
            # exactly what furniture looks like. It is also checked before the heading test
            # because some reprints set a provision's opening line in capitals —
            # `1. TAJUK RINGKAS` — which `_looks_like_heading` cannot tell apart from a genuine
            # all-capitals heading by shape alone. `_hangs_left` requires `x0` at the body margin,
            # so it can never also be true for a marginal note, which sits well to the right of it.
            role = "provision"
        elif (
            line.x0 - body_margin > width * _MARGIN_OFFSET and len(line.text) <= _MARGIN_MAX_CHARS
        ):
            # Checked before the furniture test as well, for the same reason: a short marginal
            # note positioned near the top or bottom edge of the page — annotating the first or
            # last provision on it — masks and repeats exactly like a running head would. A
            # genuine running head sits at the body margin, not far to the right of it, so this
            # ordering does not risk misreading one as a note.
            role = "marginal"
        elif (_furniture_key(line.text), in_header) in furniture:
            role = "header" if in_header else "footer"
        elif line.size >= body_size * _HEADING_SIZE_RATIO or _looks_like_heading(line.text):
            role = "heading"
        else:
            role = "body"
        classified.append(
            Line(
                page=line.page,
                x0=line.x0,
                y=line.y,
                size=line.size,
                font=line.font,
                text=line.text,
                role=role,
            )
        )
    return tuple(classified)


def _hangs_left(line: Line, body_margin: float) -> bool:
    """Whether the line opens a numbered provision at the hanging left margin."""
    if line.x0 > body_margin + 1.0:
        return False
    from billwatcher.legislation.vocabulary import parenthesised, provision_number

    return provision_number(line.text) is not None or parenthesised(line.text) is not None


def _looks_like_heading(text: str) -> bool:
    """An all-capitals line of words is a heading even when set at body size."""
    letters = [character for character in text if character.isalpha()]
    if len(letters) < 4:
        return False
    return all(character.isupper() for character in letters)


def _repeated_furniture(
    lines: list[Line], boxes: dict[int, PageBox], *, page_count: int
) -> frozenset[tuple[str, bool]]:
    """Lines that repeat near the same edge on most pages: running heads and running feet.

    A document of one or two pages has no repetition to observe, so nothing is furniture and
    every line is kept. Withholding content is worse than keeping a running head.
    """
    if page_count < 3:
        return frozenset()
    seen: dict[tuple[str, bool], dict[int, float]] = {}
    for line in lines:
        box = boxes.get(line.page)
        height = box.height if box else 1.0
        relative_y = line.y / height if height else 0.0
        if not (relative_y >= _HEADER_BAND or relative_y <= _FOOTER_BAND):
            continue
        key = (_furniture_key(line.text), relative_y >= _HEADER_BAND)
        seen.setdefault(key, {}).setdefault(line.page, relative_y)
    threshold = max(2, round(page_count * _REPEAT_FRACTION))
    return frozenset(
        key
        for key, appearances in seen.items()
        if len(appearances) >= threshold and _is_fixed_baseline(appearances.values())
    )


def _is_fixed_baseline(positions: Iterable[float]) -> bool:
    """Whether repeated occurrences sit at the same height on every page.

    This is what separates a running head from a heading that merely recurs. `BAHAGIAN I` opens
    two Parts at whatever height the preceding text left off; `Akta 710` is printed at the same
    baseline on every page. Without this test a Part heading near the top of a short document is
    discarded as furniture, which deletes real structure.
    """
    values = sorted(positions)
    return bool(values) and (values[-1] - values[0]) <= _BASELINE_TOLERANCE


_DIGITS = re.compile(r"\d+")


def _furniture_key(text: str) -> str:
    """A running head's identity, with the page-varying digits removed.

    `Akta 710      12` and `Akta 710      13` are the same running head; comparing raw text
    would call them two different lines and keep both.
    """
    return _DIGITS.sub("#", text.casefold())


def _modal(values: Iterable[float]) -> float:
    """The most common value, breaking a tie towards the smaller one."""
    counted = Counter(values)
    if not counted:
        return 0.0
    best = max(counted.values())
    return float(min(value for value, total in counted.items() if total == best))


def _weighted_modal(pairs: Iterable[tuple[float, int]]) -> float:
    """The value carrying the most text, breaking a tie towards the smaller one.

    The body column is where the words are: it is the leftmost of the sizes and margins that
    hold the most characters, which is true of a contents page and a schedule alike.
    """
    totals: dict[float, int] = {}
    for value, weight in pairs:
        totals[value] = totals.get(value, 0) + weight
    if not totals:
        return 0.0
    best = max(totals.values())
    return float(min(value for value, total in totals.items() if total == best))


def _failed(started: float, error: str) -> LayoutDocument:
    return LayoutDocument(
        extractor_name=EXTRACTOR_NAME,
        extractor_version=LAYOUT_EXTRACTOR_VERSION,
        status="failed",
        duration_ms=round((time.monotonic() - started) * 1000),
        error=error[:1000],
    )
