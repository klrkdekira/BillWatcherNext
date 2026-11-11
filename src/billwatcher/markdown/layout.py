"""Layout-aware reading of a legislative PDF (HANDOFF 26.1).

Naive text extraction loses the structure Malaysian legislative typography carries in position:
section numbers hang at the left margin, marginal notes sit in the right margin *on the same
baseline as the text they annotate*, running heads and page numbers repeat, and schedules
restart numbering. The Postgres-backed flat-text reader (now `legacy/`) deliberately produced
flat page text for
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

Position is not the only thing the typography carries, and reading it as though it were is what
this module got wrong for a corpus-wide release. Malaysian legislative printing marks structure
with **weight** as much as with position: a section heading is set in the body's own size, in
bold, and a provision's number is bold with the sentence after it in roman. A reader that looks
only at size and left margin therefore finds no headings at all in a document full of them, and
misses every subsection, because a subsection is *indented* rather than hung. Both signals are
read here now, and `Line` carries the face as well as the box.
"""

import io
import re
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTChar, LTPage, LTTextContainer, LTTextLine

from billwatcher.download.normalize import normalize_text
from billwatcher.version import LAYOUT_EXTRACTOR_VERSION

# A bound on work done for one document. The corpus's largest bill is well under this; a PDF
# claiming more pages is refused rather than allowed to occupy a worker indefinitely.
MAX_PAGES = 2000

# Bands measured from the top and bottom of the page in which a *repeated* line is running
# furniture rather than content.
#
# The header band was 0.92, and Parliament does not typeset that high: measured over a corpus
# sample, every repeating fixed-baseline line sits at 0.88-0.91 of the page box. The band cleared
# all of them, so no running head in the corpus was ever a candidate for furniture and every one
# of them was published as content — a stray `Bill 2` block on every other page of every reading.
# Widening it is safe because the band only decides *candidacy*: a line still has to repeat at a
# fixed baseline across most pages, and Part headings, numbered provisions and marginal notes are
# each recognised before the furniture test can reach them.
_HEADER_BAND = 0.87
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

# Known limit: a *table* is read as flowing text. Nothing here reconstructs columns, so a
# schedule's rows arrive as one run-on paragraph, and a cell far enough right of the body margin
# can be classified as a marginal note — `Total`, the last column header of a contribution table,
# is the measured example. Recovering the grid needs column detection this module does not have,
# and reading the cells in order is still better than dropping them: every word reaches the
# markdown, in the order it is printed, which is what the fidelity gate scores. The prose around
# the table is unaffected, and that is where the provisions are.

# ...and only if those repetitions sit at the same height, as a fraction of the page. A
# running head has a fixed baseline; a heading that happens to recur near the top does not.
_BASELINE_TOLERANCE = 0.01

# A line starting this far right of the body margin, as a fraction of page width, is in the
# margin column rather than the text column.
_MARGIN_OFFSET = 0.45

# A marginal note is short. A long line starting right of the column is an indented block.
_MARGIN_MAX_CHARS = 80

# The 1990s printings set the marginal note in the *outer* margin, so on every other page it is
# to the left of the text column, in small type — `Pindaan` / `seksyen 6A.` beside `4. Seksyen 6A
# Akta ibu...`. pdfminer separates it cleanly; the reader then sorted it into the body by baseline,
# because the only margin it knew was the right-hand one, and the note's words landed inside the
# provision they annotate (`Pindaan 4. Seksyen HB Akta ibu adalah dipinda, dalam subsekyen seksyen
# HB. (2), dengan...`). Measured: the residue of the parser audit's 546 rejected readings is 275
# documents from the 1990s, and this shape is in most of them. A left-margin line is one that
# *ends* before the body column begins and starts well left of it — the end test is what tells it
# from a provision number hanging at the margin with its sentence running on to the right.
_LEFT_MARGIN_OFFSET = 0.06
_LEFT_MARGIN_CLEARANCE = 2.0

# A small-capitals face: `Times-Roman-SC700`, the small caps at 70% of the size. Its glyphs are
# capitals on the page, but the reading carried them as a mix of cases (`FIrst s chedule`,
# `BAhAgiAN`, `JAdUAL PertAmA`) with a word break wherever pdfminer's word inference measured a
# small glyph's gap against a small glyph's width. The face names itself, so the line is set as it
# prints — in capitals — and its words are rebuilt from geometry as a tracked line's are.
_SMALL_CAPS_FONT = re.compile(r"-SC\d*$|smallcaps|smcp", re.IGNORECASE)

# A heading is set larger than the body. Below this ratio the difference is font rounding.
_HEADING_SIZE_RATIO = 1.08

# What counts as "the size the prose is set in". Not the size carrying the most characters, which
# is what this used to be and what got it wrong: an amending bill is mostly *schedules*, and a
# schedule is set in table type two points smaller than the prose around it. Measured on
# `DR 11/2024 BI`, 10pt table type carries 3,649 characters against the prose's 1,267, so the
# modal size was the table's — and every line of actual legal text then sat above
# `_HEADING_SIZE_RATIO` and was classified as a heading. The whole document came back as headings.
#
# Headings are set *larger* than the body and are a small share of the text; small print is set
# smaller and can be most of it. So the body size is the largest size that still carries a real
# share of the document, and everything above it is display type.
#
# The share itself is not delicate: swept over a 50-document sample at 0.05, 0.10, 0.15, 0.20 and
# 0.25, the median heading ratio moved from 0.214 to 0.220 and no value left a single document
# reading as mostly headings. What mattered was taking the largest qualifying size rather than the
# modal one. 0.15 sits in the middle of the range that behaves identically.
_BODY_SIZE_MIN_SHARE = 0.15

# Malaysian legislative typography marks a heading by weight, not by size: "Short title and
# commencement" is set in the same 12pt as the provision beneath it, in bold. Relying on size
# alone therefore missed every section heading in the corpus — they were read as body text and
# joined into the paragraph that followed. Both signals are kept, because they are independent:
# some reprints set headings larger, most set them bold.
_BOLD_FONT = re.compile(r"bold|black|heavy|semibold|demi", re.IGNORECASE)
_ITALIC_FONT = re.compile(r"italic|oblique", re.IGNORECASE)

# ...but only while bold is the exception. A document typeset entirely in a bold face has no
# emphasis to read, and calling every line a heading is the failure this rule exists to prevent.
_MAX_BOLD_SHARE = 0.4

# How much bigger than the ordinary line spacing a gap has to be before it separates two typeset
# blocks rather than two lines of one paragraph. Measured on the corpus: prose leads at 13.8pt and
# the space before a new provision is 27.6pt, so anything close to half again is a block break.
_BLOCK_GAP_RATIO = 1.4

# A page number never wears brackets: `(c)` or `(3)` at the very top of a page is the paragraph or
# subsection that happens to open it, and reading it as a page number discarded the token and the
# line beside it as a running head — the first line of the page, lost (measured: 16 readings
# rejected for exactly the paragraph that opened a page). A full stop is allowed: one printing
# numbers its verso pages `4.` beside the running head. What tells that `4.` from the clause number
# `7.` hanging on a page's last baseline is `_page_numbers` below.
_PAGE_NUMBER_RE = re.compile(r"^[^\w()]*(?:\d{1,4}|[ivxlcdm]{1,7})[^\w()]*$", re.IGNORECASE)

ROLES = frozenset({"body", "heading", "provision", "marginal", "header", "footer", "page_number"})

EXTRACTOR_NAME = "pdfminer-layout"


@dataclass(frozen=True, slots=True)
class Line:
    """One typeset line, with the geometry that decides what it is.

    `font` is the face most of the line is set in and `lead_font` the face of its first glyph.
    They differ exactly where it matters: a provision's opening line prints its *number* in bold
    and the sentence after it in roman, so the lead font is what marks `2.` as the start of a
    provision rather than a wrapped continuation, while the modal font is what tells a wholly
    bold section heading apart from that same line.
    """

    page: int
    x0: float
    y: float
    size: float
    font: str | None
    text: str
    role: str
    lead_font: str | None = None
    opens_block: bool = False
    x1: float = 0.0
    """Where the line ends. `0.0` means the reader that built this line did not record it."""
    indent: float = 0.0
    """How far right of its page's text column the line begins, in points; negative hangs left.

    The one geometric fact the structure parser needs and the markdown cannot carry (ADR-042): a
    provision number set deeper than the bill's own clauses is a section quoted from another Act,
    a token at the depth of the paragraph list it continues is a paragraph, and neither can be told
    from the text alone.
    """
    """Whether a block of vertical space precedes this line, separating it from the one above.

    Carried on the line because only the reader can measure it — it is a fact about this
    document's own leading, and the assembly step in `markdown.reading` sees the content lines
    with the furniture already removed, so it cannot recover the spacing itself. Without it a
    paragraph break that is marked by space alone, rather than by a number or a heading, is
    invisible and two typeset blocks run together.
    """

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

    A line that *begins* outside the page box is not on the printed page. One reading carried a
    second copy of its last pages' text drawn from x = -9, beside `RAHSIA` stamps at the same
    offset — a mis-registered layer, invisible on paper and duplicated in the text — and read every
    clause and schedule heading on those pages twice. Only when the page has text inside the box
    is text outside it discarded: a page whose every line sits at negative x is a coordinate quirk,
    not an empty page.
    """
    items = [
        item
        for element in page
        if isinstance(element, LTTextContainer)
        for item in element
        if isinstance(item, LTTextLine)
    ]
    left_edge = float(page.bbox[0])
    on_page = [item for item in items if float(item.x0) >= left_edge - _OFF_PAGE_TOLERANCE]
    if on_page:
        items = on_page
    lines: list[Line] = []
    for item in items:
        text = normalize_text(item.get_text())
        if not text:
            continue
        glyphs = [glyph for glyph in item if isinstance(glyph, LTChar)]
        font = _modal_font(glyphs)
        if _is_small_caps(font):
            text = (normalize_text(_rejoin_tracked(glyphs)) or text).upper()
        elif _looks_tracked(text):
            text = normalize_text(_rejoin_tracked(glyphs)) or text
        lines.append(
            Line(
                page=number,
                x0=float(item.x0),
                x1=float(item.x1),
                y=float(item.y0),
                # The modal glyph size, so one superscript does not demote a heading.
                size=_modal(round(float(glyph.size), 1) for glyph in glyphs),
                # The modal face, for the same reason: a bold provision number at the head of
                # an otherwise roman sentence must not make the whole line read as a heading.
                font=font,
                text=text,
                role="body",
                lead_font=str(glyphs[0].fontname) if glyphs else None,
            )
        )
    lines.sort(key=lambda line: (-line.y, line.x0))
    return lines


# How far left of the page box a line may begin and still count as printed on the page: a rounding
# margin, not a tolerance for overhang.
_OFF_PAGE_TOLERANCE = 1.0

# How close two baselines have to be, in points, to count as the same printed line. A running head
# and the page number beside it are set on one baseline; pdfminer reports them a fraction of a
# point apart because they are separate text containers.
_SAME_BASELINE = 1.0


def _looks_tracked(text: str) -> bool:
    """Whether pdfminer read part of this line as a scatter of single letters.

    A bill's HURAIAN pages are set with letterspacing ("R a n g U n d a n g - U n d a n g i n i
    b e r t u j u a n"), and pdfminer's word inference — a fixed margin against the glyph advance
    — reads every tracked letter as its own word. The trigger is a run of three or more
    single-letter tokens, which no real sentence in either of the corpus's languages produces —
    their only one-letter words are "a" and "I", and neither repeats — but a tracked word always
    does ("s u a tu", "B i l l"). Only such lines are rebuilt, so an ordinarily set line can
    never be re-segmented into something worse.
    """
    run = 0
    for token in text.split():
        run = run + 1 if len(token) == 1 and token.isalpha() else 0
        if run >= 3:
            return True
    return False


def _rejoin_tracked(glyphs: list[LTChar]) -> str:
    """Rebuild a tracked line's text from glyph geometry instead of pdfminer's word inference.

    Two signals, and a break is any gap above the larger of them. The absolute one is a quarter
    em: measured across the corpus, adjacent letters sit 0–0.5pt apart in ordinary type and
    1–2pt apart when tracked, while the space between words is 2.5pt and up — so 0.25 × the
    line's type size splits letters from words even on a line that is only partly tracked
    ("This B i l l seeks to amend…", where the median gap is an ordinary letter's). The relative
    one is twice the median positive gap, which is what carries a flourish letterspaced with real
    space glyphs ("b e r n a m a"): its letters sit a uniform space-plus-tracking apart, wider
    than a quarter em, and only its word gaps are wider still. Space glyphs are dropped and the
    geometry decides — the word on the paper is *bernama*, the spacing is presentation, and the
    reading carries the word.
    """
    letters = [glyph for glyph in glyphs if glyph.get_text().strip()]
    if not letters:
        return ""
    gaps = [letters[i + 1].x0 - letters[i].x1 for i in range(len(letters) - 1)]
    positive = sorted(gap for gap in gaps if gap > 0.05)
    tracking = positive[len(positive) // 2] if positive else 0.0
    size = _modal(round(float(glyph.size), 1) for glyph in letters)
    threshold = max(tracking * 2.0, size * 0.25, 0.6)
    pieces = [letters[0].get_text()]
    for gap, glyph in zip(gaps, letters[1:], strict=True):
        if gap > threshold:
            pieces.append(" ")
        pieces.append(glyph.get_text())
    return "".join(pieces)


def _is_small_caps(font: str | None) -> bool:
    """Whether a face is a small-capitals face, by its own name."""
    return bool(font) and _SMALL_CAPS_FONT.search(str(font).rsplit("+", 1)[-1]) is not None


def _carries_text(text: str) -> bool:
    """Whether a line has any word or figure in it, rather than only punctuation.

    A marginal note is an annotation on a provision, so it says something. A cover page's empty
    citation bracket prints `[` in the text column and `]` far to its right, and the right-hand
    half lands in the margin column and was read as a note — 1,793 `<!-- marginal: ] -->` comments
    across the corpus, each one half of a bracket pair torn apart. Rejecting it here lets the line
    fall through to `body`, where it rejoins its own `[` in reading order.
    """
    return any(character.isalnum() for character in text)


def _page_numbers(lines: list[Line], boxes: dict[int, PageBox]) -> frozenset[int]:
    """Indices of the lines that are page numbers.

    A page number reads as one (`_PAGE_NUMBER_RE`), sits in the header or footer band, and is
    among the first or last lines printed on its page. The rank test is what tells it from a
    clause number: `7.` hanging on a page's last baseline reads as a page number and sits in the
    footer band, but its own text runs on beside it and a wrapped line sits beneath, so it is not
    the last thing on the page (measured: clause 7 of one bill lost with its number). A number
    whose neighbour on the baseline opens with a bracket — `7.` beside `(1) Segala tanah`, the
    clause's first subsection — or runs to a sentence's length is that clause's number even at
    the very edge: a running head is a short title and never begins with a bracket. And a page
    carries one page number at each edge, so `17.` beneath the `70` already printed at the top
    of its page is the item that opens the page, not a second number for it (measured: a
    Schedule's paragraph 17 lost with its number).
    """
    ranks = _ranks_on_page(lines)
    found: set[int] = set()
    taken: set[tuple[int, bool]] = set()
    for index, line in enumerate(lines):
        box = boxes.get(line.page)
        height = box.height if box else 1.0
        relative_y = line.y / height if height else 0.0
        in_header = relative_y >= _HEADER_BAND
        if not (in_header or relative_y <= _FOOTER_BAND):
            continue
        if not _PAGE_NUMBER_RE.match(line.text):
            continue
        if not _is_at_the_edge_of_its_page(ranks[index], in_header=in_header):
            continue
        if (line.page, in_header) in taken:
            continue
        if any(
            other.page == line.page
            and other is not line
            and abs(other.y - line.y) <= _SAME_BASELINE
            and (
                other.text.lstrip().startswith("(")
                or len(other.text.strip()) > _RUNNING_HEAD_MAX_CHARS
            )
            for other in lines[max(0, index - 3) : index + 4]
        ):
            continue
        found.add(index)
        taken.add((line.page, in_header))
    return frozenset(found)


# The longest a running head beside a page number runs to. `Kerajaan Tempatan (Pindaan)` and
# `Rang Undang-Undang` are the corpus's shapes; a provision's first line beside its hanging number
# is a sentence and runs past this.
_RUNNING_HEAD_MAX_CHARS = 50


def _beside_a_page_number(
    lines: list[Line], boxes: dict[int, PageBox], page_numbers: frozenset[int]
) -> frozenset[int]:
    """Indices of lines printed on the same baseline as a page number, at the edge of their page.

    The one running-head signal that needs no other page to confirm it. A page number is
    recognised from its own text, so a line sharing its baseline is the running head beside it —
    which is exactly what the docstring of `_EDGE_RANK` already observes, used here as evidence
    rather than only as a reason for the rank threshold.

    The edge-rank test is kept: it is what stops a body line that happens to sit level with a
    page number printed in the *footer* margin from being discarded with it.
    """
    ranks = _ranks_on_page(lines)
    numbers: dict[int, list[float]] = {}
    for index in page_numbers:
        numbers.setdefault(lines[index].page, []).append(lines[index].y)

    beside: set[int] = set()
    for index, line in enumerate(lines):
        if index in page_numbers:
            continue
        box = boxes.get(line.page)
        height = box.height if box else 1.0
        relative_y = line.y / height if height else 0.0
        in_header = relative_y >= _HEADER_BAND
        if not (in_header or relative_y <= _FOOTER_BAND):
            continue
        if not _is_at_the_edge_of_its_page(ranks[index], in_header=in_header):
            continue
        if any(abs(line.y - y) <= _SAME_BASELINE for y in numbers.get(line.page, ())):
            beside.add(index)
    return frozenset(beside)


def _is_structural_heading(text: str) -> bool:
    """Whether a line is recognisable as a Part/Chapter/Schedule heading regardless of position."""
    from billwatcher.graph.vocabulary import container_heading, schedule_heading

    return container_heading(text) is not None or schedule_heading(text) is not None


def _classify(lines: list[Line], pages: list[PageBox]) -> tuple[Line, ...]:
    """Assign each line a role from its geometry and from what repeats across pages."""
    # Imported here, as everywhere else in this module: `graph.vocabulary` is the structural
    # vocabulary and importing it at module scope would make the reader depend on the graph.
    from billwatcher.graph.vocabulary import is_bare_unit_label

    if not lines:
        return ()
    boxes = {page.number: page for page in pages}
    # Weighted by how much text sits at each size and margin, not by how many lines do. Counting
    # lines lets a page of short marginal notes outvote the body column that holds the document.
    body_size = _body_size(lines)
    body_margin = _text_column((round(line.x0), len(line.text)) for line in lines)
    page_margins = _page_margins(lines, fallback=body_margin)
    emphasis_is_readable = _bold_share(lines) < _MAX_BOLD_SHARE
    leading = _leading(lines)
    gaps = _gaps_before(lines)
    furniture = _repeated_furniture(lines, boxes, page_count=len(pages))
    page_numbers = _page_numbers(lines, boxes)
    beside_page_number = _beside_a_page_number(lines, boxes, page_numbers)

    classified: list[Line] = []
    for index, line in enumerate(lines):
        box = boxes.get(line.page)
        height = box.height if box else 1.0
        width = box.width if box else 1.0
        body_margin = page_margins.get(line.page, body_margin)
        relative_y = line.y / height if height else 0.0
        in_header = relative_y >= _HEADER_BAND

        if index in page_numbers:
            role = "page_number"
        elif index in beside_page_number:
            # A running head, recognised from *this* page alone rather than from repetition
            # across pages. `_repeated_furniture` needs three pages to observe anything and a
            # verso/recto pair needs six, so on a two-page bill the head was kept as content and
            # `Rang Undang-Undang` turned up as a stray paragraph under the page marker (measured:
            # 143 documents, the single largest source of leaked furniture in the corpus).
            role = "header" if in_header else "footer"
        elif _is_structural_heading(line.text):
            # A Part, Chapter, or Schedule heading is checked *before* the furniture test,
            # deliberately. A document that opens each Part on a fresh page can place its heading
            # near the top of most pages, at a consistent baseline — which is exactly what a
            # running head also looks like. Digit-masking alone cannot tell "BAHAGIAN 1" on page 1
            # apart from "BAHAGIAN 2" on page 8 from "Akta 710   12" and "Akta 710   13": both
            # collapse to the same masked key and repeat near a fixed baseline. Recognising the
            # line as structure first is what stops real Parts from being erased as furniture.
            role = "heading"
        elif not _in_margin_column(line, body_margin, width) and _opens_a_provision(
            line, body_margin, gap_before=gaps[index], leading=leading
        ):
            # Checked before both the furniture test and the heading test, deliberately, and for
            # the same reason as the structural heading above: a numbered provision can land in
            # the header or footer band exactly as easily as a Part heading can — a short Act, or
            # a page whose preceding text runs long, can leave a section's own opening line
            # sitting above the header threshold. `Seksyen 1.` on one page and `Seksyen 2.` on the
            # next mask to the same digit-free key and repeat at a shared baseline, which is
            # exactly what furniture looks like. It is also checked before the heading test
            # because some reprints set a provision's opening line in capitals —
            # `1. TAJUK RINGKAS` — which `_looks_like_heading` cannot tell apart from a genuine
            # all-capitals heading by shape alone. The margin column is excluded explicitly: this
            # test used to require `x0` at the body margin, which made it impossible for a
            # marginal note to satisfy, and recognising indented provisions gave that up. The
            # exclusion buys it back without costing an indent level — the deepest subparagraph
            # sits nowhere near `_MARGIN_OFFSET` of the page width from the body column.
            role = "provision"
        elif (
            _in_margin_column(line, body_margin, width)
            and len(line.text) <= _MARGIN_MAX_CHARS
            and _carries_text(line.text)
        ):
            # Checked before the furniture test as well, for the same reason: a short marginal
            # note positioned near the top or bottom edge of the page — annotating the first or
            # last provision on it — masks and repeats exactly like a running head would. A
            # genuine running head sits at the body margin, not far to the right of it, so this
            # ordering does not risk misreading one as a note.
            role = "marginal"
        elif (
            _in_left_margin(line, body_margin, width)
            and len(line.text) <= _MARGIN_MAX_CHARS
            and _carries_text(line.text)
        ):
            # The outer-margin note of a verso page: left of the text column, and wholly so. It
            # comes after the provision test, so a hanging number that begins left of the margin
            # and runs on into its sentence has already been claimed.
            role = "marginal"
        elif (_furniture_key(line.text), in_header) in furniture:
            role = "header" if in_header else "footer"
        elif is_bare_unit_label(line.text) and line.size < body_size * _HEADING_SIZE_RATIO:
            # The Arrangement of Clauses prints "Fasal" / "Clause" as the column header over each
            # Part's group of entries — table furniture, reprinted mid-page at whatever height the
            # preceding group ended, so no baseline or repetition test can see it. Checked after
            # the structural-heading and provision tests, so a real `Fasal 3` is never reached, and
            # guarded on size so a display-set word on a cover page is left alone.
            role = "header"
        elif (
            line.size >= body_size * _HEADING_SIZE_RATIO
            or _looks_like_heading(line.text)
            or (emphasis_is_readable and _is_bold(line.font))
        ):
            # The bold test comes last of the three, and after the provision test above, precisely
            # because a provision's opening line often *starts* bold: the number is set in bold and
            # the sentence is not. `line.font` is the modal face, so only a line that is bold
            # throughout — which is what a section heading is — reaches this.
            role = "heading"
        else:
            role = "body"
        classified.append(
            Line(
                # A line of pure punctuation never opens a block of its own: the second half of
                # a cover page's citation bracket, or an opening quote set in its own container,
                # belongs to the text it is printed against, not to a paragraph of one character.
                opens_block=(
                    _carries_text(line.text)
                    and leading > 0.0
                    and gaps[index] > leading * _BLOCK_GAP_RATIO
                ),
                page=line.page,
                x0=line.x0,
                y=line.y,
                size=line.size,
                font=line.font,
                text=line.text,
                role=role,
                lead_font=line.lead_font,
                x1=line.x1,
                indent=round(line.x0 - body_margin, 1),
            )
        )
    return tuple(classified)


# A page has to carry this much text before its own margin is trusted over the document's: a cover
# or a half-empty last page has no column to measure.
_PAGE_MARGIN_MIN_CHARS = 400


def _page_margins(lines: list[Line], *, fallback: float) -> dict[int, float]:
    """Where the text column begins on each page.

    A bound book's verso and recto pages are set to different margins — the column sits nearer
    the spine on each — so one document-wide margin is wrong on half the pages, and a marginal
    note in the outer margin of a verso page then measured as *inside* the recto column. Every
    test that reads position against the column (the provision hang, both margin columns) reads
    it against the page's own.
    """
    by_page: dict[int, list[tuple[float, int]]] = {}
    for line in lines:
        by_page.setdefault(line.page, []).append((round(line.x0), len(line.text)))
    return {
        page: (
            _text_column(pairs)
            if sum(weight for _, weight in pairs) >= _PAGE_MARGIN_MIN_CHARS
            else fallback
        )
        for page, pairs in by_page.items()
    }


# The share of a page's (or document's) characters a column has to carry to count as a column of
# text at all, rather than a hanging number, a marginal note or a stray line.
_COLUMN_MIN_SHARE = 0.12


def _text_column(pairs: Iterable[tuple[float, int]]) -> float:
    """Where the text column begins: the leftmost x0 carrying a real share of the characters.

    Not the x0 carrying the *most* characters, which is what this used to be and what went wrong
    on a page of quoted text: an amendment page is mostly the block-indented sections it inserts,
    so the modal column was the quotation's, the bill's own clause on that page measured as
    hanging sixty points into the margin, and the structure parser's depth reading (ADR-042) took
    the document's clause column from it. The body column is the leftmost one that holds text;
    everything set to the right of it — subsections, paragraphs, quotations — is indented from it.
    """
    totals: dict[float, int] = {}
    for value, weight in pairs:
        totals[value] = totals.get(value, 0) + weight
    if not totals:
        return 0.0
    floor = sum(totals.values()) * _COLUMN_MIN_SHARE
    substantial = [value for value, total in totals.items() if total >= floor]
    return float(min(substantial)) if substantial else _weighted_modal(totals.items())


def _in_margin_column(line: Line, body_margin: float, width: float) -> bool:
    """Whether the line sits in the right-hand margin rather than the text column.

    One definition, used by both the marginal-note test and the provision test that must not
    overlap it. Two copies of this condition would eventually disagree, and the way they would
    disagree is a marginal note read as a provision.
    """
    return line.x0 - body_margin > width * _MARGIN_OFFSET


def _in_left_margin(line: Line, body_margin: float, width: float) -> bool:
    """Whether the line sits wholly in the left-hand margin, before the text column begins.

    Only a line whose end was recorded can be placed here; a `Line` built without `x1` is never
    in the left margin, which keeps every earlier reading of the same geometry unchanged.
    """
    return (
        line.x1 > line.x0
        and line.x1 <= body_margin - _LEFT_MARGIN_CLEARANCE
        and body_margin - line.x0 > width * _LEFT_MARGIN_OFFSET
    )


def _opens_a_provision(
    line: Line, body_margin: float, *, gap_before: float, leading: float
) -> bool:
    """Whether this line opens a numbered provision rather than continuing one.

    The text has to begin with a number the vocabulary recognises, but that alone is not enough:
    a wrapped line can begin with a cross-reference that looks identical. Three independent
    signals say the line *starts* something, and any one of them is enough, because Malaysian
    legislative typography does not use the same one consistently:

    - **It hangs at the body margin.** The original test, and the only one for a section number.
    - **Its first glyph is set apart from the rest of the line.** A provision number is printed in
      bold and a paragraph letter in italic, with the sentence after it in roman. This is what
      catches `(2)` and `(a)`, which are *indented* rather than hanging — first-line indent for a
      subsection, deeper indent for each paragraph level — so the margin test can never see them.
      Missing them is what collapsed whole pages into a single run-on paragraph.
    - **A block of vertical space precedes it.** The fallback for a reprint that sets its numbers
      in the body face, where neither position nor emphasis distinguishes them.
    """
    from billwatcher.graph.vocabulary import parenthesised, provision_number

    if provision_number(line.text) is None and parenthesised(line.text) is None:
        return False
    if line.x0 <= body_margin + 1.0:
        return True
    if _emphasis(line.lead_font) != _emphasis(line.font):
        return True
    return leading > 0.0 and gap_before > leading * _BLOCK_GAP_RATIO


def _looks_like_heading(text: str) -> bool:
    """An all-capitals line of *words* is a heading even when set at body size.

    Words, not codes. `RM25.75 RM115.90` is two cells of a contribution table, and its only
    letters are the currency prefix — four of them, all capital, which was enough to make every
    such row a heading. Requiring letters to be most of the line keeps `BAHAGIAN II` and `A BILL`
    and rejects a row of money.
    """
    letters = [character for character in text if character.isalpha()]
    if len(letters) < 4:
        return False
    if not all(character.isupper() for character in letters):
        return False
    body = [character for character in text if not character.isspace()]
    return bool(body) and len(letters) / len(body) >= 0.5


def _emphasis(font: str | None) -> str:
    """The weight and slant of a face, with the subset tag and family name discarded.

    `AUYHWH+Times-Bold` and `IWGFDM+Times-Bold` are the same emphasis in two documents; the
    six-letter prefix is a PDF font-subset tag and carries no typographic meaning.
    """
    if not font:
        return ""
    name = font.rsplit("+", 1)[-1]
    weight = "bold" if _BOLD_FONT.search(name) else ""
    slant = "italic" if _ITALIC_FONT.search(name) else ""
    return weight + slant


def lead_emphasis(line: Line) -> str:
    """The emphasis of a line's first glyph, as `_emphasis` names it: what marks `2.` or `(a)`."""
    return _emphasis(line.lead_font)


def _is_bold(font: str | None) -> bool:
    return "bold" in _emphasis(font)


def _bold_share(lines: list[Line]) -> float:
    """The fraction of the document's characters set in a bold face."""
    total = sum(len(line.text) for line in lines)
    if not total:
        return 0.0
    return sum(len(line.text) for line in lines if _is_bold(line.font)) / total


def _body_size(lines: list[Line]) -> float:
    """The size the prose is set in: the largest that still carries a real share of the text.

    Not the modal size. See `_BODY_SIZE_MIN_SHARE` — a document whose bulk is a schedule set in
    table type would otherwise take the table's size as its body, and read every line of prose
    above it as a heading.
    """
    totals: dict[float, int] = {}
    for line in lines:
        size = round(line.size, 1)
        totals[size] = totals.get(size, 0) + len(line.text)
    if not totals:
        return 0.0
    floor = sum(totals.values()) * _BODY_SIZE_MIN_SHARE
    qualifying = [size for size, total in totals.items() if total >= floor]
    return max(qualifying) if qualifying else max(totals)


def _leading(lines: list[Line]) -> float:
    """The ordinary distance between two lines of one paragraph, as this document sets it."""
    gaps = Counter(
        round(previous.y - line.y)
        for previous, line in zip(lines, lines[1:], strict=False)
        if previous.page == line.page and 0 < previous.y - line.y < 100
    )
    return float(gaps.most_common(1)[0][0]) if gaps else 0.0


def _gaps_before(lines: list[Line]) -> list[float]:
    """The vertical space above each line, or 0 where the page above it begins.

    Computed here rather than carried on `Line`, because it is a fact about a line's neighbours
    in one reading rather than a property of the line itself.
    """
    gaps: list[float] = []
    previous: Line | None = None
    for line in lines:
        if previous is not None and previous.page == line.page and previous.y > line.y:
            gaps.append(previous.y - line.y)
        else:
            gaps.append(0.0)
        previous = line
    return gaps


def _repeated_furniture(
    lines: list[Line], boxes: dict[int, PageBox], *, page_count: int
) -> frozenset[tuple[str, bool]]:
    """Lines that repeat near the same edge on most pages: running heads and running feet.

    A document of one or two pages has no repetition to observe, so nothing is furniture and
    every line is kept. Withholding content is worse than keeping a running head.
    """
    if page_count < 3:
        return frozenset()
    ranks = _ranks_on_page(lines)
    seen: dict[tuple[str, bool], dict[int, float]] = {}
    for index, line in enumerate(lines):
        box = boxes.get(line.page)
        height = box.height if box else 1.0
        relative_y = line.y / height if height else 0.0
        in_header = relative_y >= _HEADER_BAND
        if not (in_header or relative_y <= _FOOTER_BAND):
            continue
        if not _is_at_the_edge_of_its_page(ranks[index], in_header=in_header):
            continue
        key = (_furniture_key(line.text), in_header)
        seen.setdefault(key, {}).setdefault(line.page, relative_y)
    return frozenset(
        key
        for key, appearances in seen.items()
        if _repeats_enough(appearances, page_count=page_count)
        and _is_fixed_baseline(appearances.values())
    )


# A running head is the *first* thing printed on its page, and a running foot the last. The
# baseline it shares with the page number makes that two lines rather than one.
_EDGE_RANK = 2


def _ranks_on_page(lines: list[Line]) -> list[tuple[int, int]]:
    """Each line's position from the top and from the bottom of its own page."""
    counts = Counter(line.page for line in lines)
    from_top: Counter[int] = Counter()
    ranks: list[tuple[int, int]] = []
    for line in lines:
        rank = from_top[line.page]
        from_top[line.page] += 1
        ranks.append((rank, counts[line.page] - rank - 1))
    return ranks


def _is_at_the_edge_of_its_page(rank: tuple[int, int], *, in_header: bool) -> bool:
    """Whether a line is printed at the very top or very bottom of its page.

    Position in the band is not enough on its own, and this is what makes widening the band safe.
    A body paragraph can begin high on a page whose preceding text ran short; what it cannot do is
    begin *above the running head*. Requiring a header candidate to be among the first lines
    printed on its page — and a footer candidate among the last — separates the two without
    needing to know what either says.
    """
    from_top, from_bottom = rank
    return (from_top if in_header else from_bottom) < _EDGE_RANK


def _repeats_enough(appearances: dict[int, float], *, page_count: int) -> bool:
    """Whether a line repeats often enough to be furniture rather than content.

    Measured against every page, *or* against the recto or verso pages alone. A bound book sets
    two different running heads — the Act's title on the right-hand page, `Bill` on the left —
    so each appears on only half the pages and neither clears a fraction of the whole. Both were
    consequently kept as content, and turned up in the reading as a stray `Bill 2` block on every
    other page. Counting within one parity is what recognises the pair for what it is.
    """
    if len(appearances) >= max(2, round(page_count * _REPEAT_FRACTION)):
        return True
    for parity in (0, 1):
        side = sum(1 for page in appearances if page % 2 == parity)
        pages_on_that_side = sum(1 for page in range(1, page_count + 1) if page % 2 == parity)
        if pages_on_that_side >= 3 and side >= max(2, round(pages_on_that_side * _REPEAT_FRACTION)):
            return True
    return False


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


def _modal_font(glyphs: list[LTChar]) -> str | None:
    """The face most of a line's glyphs are set in, breaking a tie towards the first one."""
    if not glyphs:
        return None
    counted = Counter(str(glyph.fontname) for glyph in glyphs)
    best = max(counted.values())
    for glyph in glyphs:
        if counted[str(glyph.fontname)] == best:
            return str(glyph.fontname)
    return None


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
