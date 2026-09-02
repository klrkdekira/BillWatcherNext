"""The cheap markdown reading: every stored PDF, read locally, with no model in the loop.

ADR-035 makes this the pipeline's first tier. The expensive tier (MinerU, a vision-language model
reading a rendered page image) is 27,833 calls for this corpus, and spending it on *first contact*
with every document leaves nothing to check the reading against. Spending it on the second reading
instead — of a corpus the local tier has already read in minutes — turns the same budget into a
cross-check, which is the one thing Gate P1 cannot do: it scores a provision tree against the
markdown it was read from, never against the page.

Nothing here parses a PDF itself. `billwatcher.markdown.layout` already reads one into
classified, geometry-bearing lines, and it already encodes the case that decides this whole
question: **a marginal note is typeset on the same baseline as the provision it annotates**, so a
reader that joins them splices an annotation into the middle of the legal text (ADR-016, measured).
This module is only the assembly of those roles into markdown, which is why it is versioned apart
from the reader underneath it.

Conventions are borrowed, not invented, so the two readings are comparable line for line:
`<!-- page N -->` page boundaries from `mineru.markdown.pages_to_markdown`, and the same
`succeeded`/`empty`/`failed` status vocabulary as `mineru.service` and `scraper.parse_document`.
"""

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any

from billwatcher.download.documents import VERSION as DOCUMENT_VERSION
from billwatcher.download.documents import document_languages
from billwatcher.markdown.imports import (
    MarkdownImportError,
    Producer,
    import_markdown,
)
from billwatcher.markdown.layout import Line, extract_layout
from billwatcher.provenance import needs_rebuild
from billwatcher.reporting import (
    Progress,
    StepFailure,
    StepResult,
    announce,
    describe_error,
)
from billwatcher.store import PipelineStore, StoredDocumentRef, keys_for, sha256_of
from billwatcher.version import LOCAL_READING_VERSION

EXTRACTOR_NAME = "pdfminer-layout"
MODE = "geometry"

# A lone letter between spaces: what kerned display typesetting looks like once it is read as text
# ("Suatu Akta u n t uk meminda"). Measured on the body only — a bill's *cover* prints
# "b e r n a m a" letter-spaced deliberately, so counting page one would flag every document in the
# corpus for a flourish that is in the paper. "a", "A" and "I" are excluded: they are the two
# languages' only real one-letter words, and an English bill's articles alone put it near the
# threshold; damage scatters every letter, so their absence costs the signal nothing. A letter
# labelling a number ("B 4", "B 10") is excluded too: a Supply Bill's schedule stamps its vote
# code beside every amount, and damage is followed by more letters, never by a figure.
_LONE_LETTER_RE = re.compile(r"(?:(?<=\s)|^)[b-zB-HJ-Z](?=\s)(?!\s*[\d(])")

# Any heading level, not just `##`: headings carry a level now (`_heading_level`), and a measure
# that counted only the top one would report a document of section headings as having none.
_HEADING_BLOCK_RE = re.compile(r"^#{1,6} ")

# Where a reading stops being worth trusting without a second opinion. Both thresholds are set from
# the measured corpus, not from taste.
#
# Re-measured over all 2,461 readings after the reader learned to read weight as well as position
# (LAYOUT_EXTRACTOR_VERSION 2.0.0): heading share has a median of 0.235 and a 90th percentile of
# 0.353, so 0.5 still sits well above ordinary variation. What changed is what it catches. It used
# to fire on 329 readings — one in seven, with a 90th percentile of 0.681 and a worst case of 0.90
# — because a document whose bulk was a small-type schedule had its *prose* classified as heading.
# That was a defect in the reader, not a property of those documents, and it now fires on 19, worst
# case 0.67.
#
# The lone-letter rate stopped measuring tracking and started measuring damage. Letterspaced body
# text — a bill's HURAIAN pages, 242 of the 244 readings this used to flag — is rejoined from
# glyph geometry since LAYOUT_EXTRACTOR_VERSION 2.2.0, and a tracked run inside an ordinary line
# since 2.4.0. What fires now (re-measured over all 2,479 readings: 5 for lone letters, 4 for
# headings, 9 in all) is the residue no geometry recovers — glyph soup scattered by a complex
# page, 1999-era scans whose metrics defeat the rebuild, and table-heavy estimates papers — which
# is exactly what the cross-check tier exists for, so they are flagged rather than repaired.
SUSPECT_HEADING_RATIO = 0.5
SUSPECT_LONE_LETTER_RATE = 6.0
# A ratio over a handful of blocks, or a rate over a few hundred bytes, is noise wearing a
# threshold: a two-page bill's body is one page of text, where two stray letters read as a rate
# of twelve. Each signal therefore needs a minimum sample before it can flag anything.
SUSPECT_MIN_BLOCKS = 40
SUSPECT_MIN_LONE_LETTERS = 15

# Roles that open a block of their own rather than continuing the paragraph in progress.
_HEADING_ROLES = frozenset({"heading"})
_OPENING_ROLES = frozenset({"provision"})


@dataclass(frozen=True, slots=True)
class LocalReading:
    """One local markdown reading. Field-for-field comparable with `MineruExtraction`."""

    extractor_name: str
    extractor_version: str
    mode: str
    status: str
    markdown: str
    markdown_sha256: str
    page_count: int
    char_count: int
    duration_ms: int
    error: str | None = None
    quality: dict[str, float] = field(default_factory=dict)
    blocks: tuple[dict[str, Any], ...] = ()
    """One geometry record per markdown block, in order (ADR-042); see `assemble_markdown`."""

    @property
    def suspect(self) -> bool:
        """Whether this reading should not be trusted without the expensive tier's opinion.

        Not a failure: a suspect reading is still the best local reading of the document, and it is
        still written. It is a statement about *where to spend the cross-check first* — which is the
        whole point of reading cheaply before reading expensively.
        """
        return (
            self.quality.get("heading_ratio", 0.0) >= SUSPECT_HEADING_RATIO
            and self.quality.get("blocks", 0.0) >= SUSPECT_MIN_BLOCKS
        ) or (
            self.quality.get("lone_letter_rate", 0.0) >= SUSPECT_LONE_LETTER_RATE
            and self.quality.get("lone_letters", 0.0) >= SUSPECT_MIN_LONE_LETTERS
        )


# Why a stored PDF has no reading, spelled once. `coverage` matches on this to tell a document
# that *cannot* be read locally apart from one that simply has not been read yet — re-running the
# step will never produce a reading for the first kind, so reporting them together would send an
# operator to run a step that is already finished.
NO_TEXT_LAYER = (
    "no text layer: the local reading found nothing; only the cross-check tier can read this "
    "document"
)


def read_document_markdown(content: bytes) -> LocalReading:
    """Read stored PDF bytes into markdown. Pure: no network, no model, no store."""
    started = time.monotonic()
    document = extract_layout(content)
    if document.status == "failed":
        return _result(started, "failed", "", 0, error=document.error)
    markdown, blocks = assemble_markdown(document.content_lines())
    status = "succeeded" if markdown.strip() and _has_body(markdown) else "empty"
    return _result(started, status, markdown, document.page_count, blocks=blocks)


def measure(markdown: str) -> dict[str, float]:
    """Two cheap signals for how much this reading needs a second opinion.

    `heading_ratio` catches the classifier deciding that most of a document is a heading, which is
    what a reprint set in an unusual font produces. `lone_letter_rate` catches kerned glyphs read as
    separate words. Neither can be repaired from the text — the geometry or the encoding is what it
    is — so they are reported rather than corrected.
    """
    blocks = [
        block
        for block in markdown.split("\n\n")
        if block.strip() and not block.strip().startswith("<!--")
    ]
    pages = markdown.split("<!-- page ")
    body = "<!-- page ".join(pages[2:]) if len(pages) > 2 else ""
    lone_letters = len(_LONE_LETTER_RE.findall(body))
    return {
        "heading_ratio": (
            round(sum(1 for b in blocks if _HEADING_BLOCK_RE.match(b)) / len(blocks), 4)
            if blocks
            else 0.0
        ),
        "lone_letter_rate": (round(lone_letters / (len(body) / 1000), 2) if body else 0.0),
        # The sample sizes behind the two ratios, so `suspect` can refuse to read a ratio taken
        # over almost nothing (see SUSPECT_MIN_BLOCKS / SUSPECT_MIN_LONE_LETTERS).
        "blocks": float(len(blocks)),
        "lone_letters": float(lone_letters),
    }


def lines_to_markdown(lines: tuple[Line, ...]) -> str:
    """The markdown alone; see `assemble_markdown` for the geometry that goes beside it."""
    return assemble_markdown(lines)[0]


def assemble_markdown(lines: tuple[Line, ...]) -> tuple[str, list[dict[str, Any]]]:
    """Assemble classified lines into markdown, one block per typeset block — and its geometry.

    The second value is one record per block, in the block's order, so `markdown.split("\n\n")`
    and the list line up index for index (ADR-042). Each record carries the block's first line's
    `indent` from the page's text column, its `role`, and the emphasis of its first glyph — the
    facts the reader measured and the markdown cannot hold, kept beside it rather than encoded into
    it, so the markdown stays the plain reading a person or another tool can consume unchanged.

    Marginal notes become HTML comments rather than text. That is the load-bearing choice here.
    They are annotations on the enacted text, not part of it, so emitting them inline would do
    exactly what ADR-016 exists to prevent — and it would also depress Gate P1's coverage, which
    scores a provision tree against every token of this markdown: an annotation no tree can
    contain would count against a faithful reading. As a comment the note survives in the artifact
    for an operator to read, is dropped by the gate's `_extractor_view` along with the page
    markers, and can never be spliced into a provision.
    """
    blocks: list[str] = []
    geometry: list[dict[str, Any]] = []
    paragraph: list[str] = []
    opener: Line | None = None
    page = 0

    def record(line: Line, kind: str) -> None:
        geometry.append(
            {
                "page": line.page,
                "indent": round(line.indent, 1),
                "role": kind,
                "lead": _lead_emphasis(line),
            }
        )

    def flush() -> None:
        if paragraph and opener is not None:
            blocks.append(" ".join(paragraph))
            record(opener, opener.role)
            paragraph.clear()

    for line in lines:
        if line.page != page:
            flush()
            page = line.page
            blocks.append(f"<!-- page {page} -->")
            record(line, "page")
        text = line.text.strip()
        if not text:
            continue
        if line.opens_block:
            # A paragraph break marked by space alone. Malaysian bills separate the enacting
            # formula from the long title, and a schedule's preamble from its items, with vertical
            # space and nothing else — no number, no heading — so a reader that breaks only on a
            # role change runs them together into one block.
            flush()
        if line.role == "marginal":
            flush()
            blocks.append(f"<!-- marginal: {_comment_safe(text)} -->")
            record(line, "marginal")
        elif line.role in _HEADING_ROLES:
            flush()
            blocks.append(f"{'#' * _heading_level(text)} {text}")
            record(line, "heading")
        elif line.role in _OPENING_ROLES:
            flush()
            opener = line
            paragraph.append(text)
        else:
            if not paragraph:
                opener = line
            paragraph.append(text)
    flush()
    return "\n\n".join(blocks), geometry


def _lead_emphasis(line: Line) -> str:
    """`bold`, `italic`, `bolditalic` or `` for the face of the block's first glyph."""
    from billwatcher.markdown.layout import lead_emphasis

    return lead_emphasis(line)


def _heading_level(text: str) -> int:
    """`##` for a division of the document, `###` for one provision's own heading.

    Both are headings to the classifier, and flattening them to one level lost the only thing a
    reader needs from the distinction: `BAHAGIAN II` opens a Part that runs for pages, while
    `Pindaan seksyen 5` labels the single provision beneath it. The level is read from the text
    rather than carried on the role because the vocabulary already answers it, and answering it
    twice is how the two answers start to disagree.
    """
    from billwatcher.graph.vocabulary import (
        arrangement_heading,
        container_heading,
        schedule_heading,
    )

    if (
        container_heading(text) is not None
        or schedule_heading(text) is not None
        or arrangement_heading(text) is not None
    ):
        return 2
    # Display capitals — `A BILL`, `RANG UNDANG-UNDANG` — are the cover's own divisions, set by
    # the same typography that sets a Part heading and belonging at the same level.
    letters = [character for character in text if character.isalpha()]
    if len(letters) >= 4 and all(character.isupper() for character in letters):
        return 2
    return 3


def _comment_safe(text: str) -> str:
    """A marginal note that cannot terminate its own comment, or swallow the text after it.

    `-->` inside the note would close the comment early and leave the remainder as body text; a
    bare `>` would end the run that the gate's tag regex consumes, so the tail of the note would
    be counted as source tokens. Both are replaced rather than escaped, because the note is being
    preserved for a human reader, not round-tripped.
    """
    return text.replace("-->", "--").replace(">", ")")


def _has_body(markdown: str) -> bool:
    """Whether anything survives besides page markers and marginal comments.

    A scan with no text layer yields a file of `<!-- page N -->` and nothing else. Gate P1 already
    refuses to judge a tree against that (`no_source_text`), and calling it `succeeded` here would
    hand the next step a document nobody has read.
    """
    return any(
        line.strip() and not line.strip().startswith("<!--") for line in markdown.splitlines()
    )


def _result(
    started: float,
    status: str,
    markdown: str,
    page_count: int,
    *,
    error: str | None = None,
    blocks: list[dict[str, Any]] | None = None,
) -> LocalReading:
    return LocalReading(
        blocks=tuple(blocks or ()),
        extractor_name=EXTRACTOR_NAME,
        extractor_version=LOCAL_READING_VERSION,
        mode=MODE,
        status=status,
        markdown=markdown,
        markdown_sha256=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        page_count=page_count,
        char_count=len(markdown),
        duration_ms=round((time.monotonic() - started) * 1000),
        error=error,
        quality=measure(markdown),
    )


def _reading_inputs(content: bytes, *, language: str, producer: Producer) -> dict[str, object]:
    """The provenance `inputs` this run would record, computed without reading the PDF.

    Assembled to match `import_markdown` exactly — same keys, same order of construction, same
    source-file shape. A drift between the two would not fail loudly: it would simply mean the
    skip below never fires, and the slow path silently returns.
    """
    return {
        "source_files": [{"file": "document.pdf", "sha256": sha256_of(content)}],
        "language": language,
        **producer.as_inputs(),
    }


class _LanguageIndex:
    """Each document's recorded language, read one bill at a time as the run walks the corpus.

    `iter_documents` yields a bill's documents together, so a one-entry cache turns 1,295 bill reads
    into 1,269 — and, more to the point, keeps the lookup next to the loop that needs it rather than
    loading the whole corpus of bill records up front to answer one question about each.
    """

    def __init__(self, store: PipelineStore) -> None:
        self._store = store
        self._slug: str | None = None
        self._languages: dict[str, str] = {}

    def of(self, ref: StoredDocumentRef) -> str | None:
        if ref.bill_slug != self._slug:
            self._slug = ref.bill_slug
            self._languages = document_languages(self._store.load_bill(ref.bill_slug) or {})
        return self._languages.get(ref.doc_key)


def _recorded_producer(store: PipelineStore, ref: StoredDocumentRef) -> str | None:
    """The tool named in this document's stored `markdown` provenance, if it has one."""
    record = store.load_provenance(
        bill_slug=ref.bill_slug, doc_key=ref.doc_key, version=ref.version, artifact="markdown"
    )
    if record is None:
        return None
    inputs = record.get("inputs")
    if not isinstance(inputs, dict):
        return None
    producer = inputs.get("producer")
    return producer if isinstance(producer, str) else None


def extract_markdown(
    store: PipelineStore,
    *,
    language: str,
    progress: Progress = None,
    replace_foreign: bool = False,
) -> StepResult:
    """Read every stored PDF locally and record the markdown through the ordinary import path.

    Deliberately not its own writer. `import_markdown` is already the one place a reading enters
    the store, and it owns the parts that are easy to get subtly wrong: the provenance record that
    decides staleness, the language cross-check against the document's own Arrangement heading, and
    the compare-before-write that makes a repeat run touch nothing. A second writer beside it would
    be a second set of those rules to keep in step.

    A reading some *other* tool produced is left alone. This step is not the only way markdown
    enters the corpus — `import-markdown` exists precisely so that an operator can read a
    difficult document with their own model, or by hand, and put the result back (ADR-021) — and
    `needs_rebuild` cannot tell that apart from staleness: an imported reading records the
    operator's own producer, which never matches this step's, so every subsequent run re-read the
    PDF and overwrote the better reading with the cheap one. Silently, and as a stage of
    `make build`, so the work was lost without anybody running the step that lost it. The producer
    is what settles it: this step owns the readings it produced and no others. `replace_foreign`
    is the deliberate override, for an operator who wants the local reading back.

    `language` is the **fallback**, not the assertion it used to be. The corpus holds both published
    languages (ADR-040) — `DR 17 BM.pdf` beside `DR 17 BI.pdf` — so one language per run would stamp
    English documents as Malay, and the language is a permanent component of the Expression IRI
    (ADR-024). Each document's own bill record answers it: `parse_listings` recorded which listing
    language named the file. `language` covers what that cannot settle — a file both languages link,
    and every document downloaded before languages were tracked — and how much of the run leaned on
    it is counted rather than assumed.
    """
    counts = {
        "documents": 0,
        "skipped_current": 0,
        "kept_foreign": 0,
        "read": 0,
        "written": 0,
        "unchanged": 0,
        "empty": 0,
        "failed": 0,
        "suspect": 0,
        "language_from_listing": 0,
        "language_fallback": 0,
    }
    failures: list[StepFailure] = []
    producer = Producer(tool=EXTRACTOR_NAME, version=LOCAL_READING_VERSION)
    refs = [ref for ref in store.iter_documents() if ref.version == DOCUMENT_VERSION]
    announce(progress, f"{len(refs)} stored document(s) to read")
    languages = _LanguageIndex(store)
    for index, ref in enumerate(refs, start=1):
        counts["documents"] += 1
        keys = keys_for(ref)
        recorded = languages.of(ref)
        counts["language_from_listing" if recorded else "language_fallback"] += 1
        doc_language = recorded or language
        content = store.load_document(**keys)
        if content is None:
            counts["failed"] += 1
            failures.append(StepFailure(ref.bill_slug, ref.doc_key, ref.version, "no stored bytes"))
            continue
        produced_by = _recorded_producer(store, ref)
        if (
            not replace_foreign
            and produced_by is not None
            and produced_by != EXTRACTOR_NAME
            and store.has_markdown(**keys)
        ):
            counts["kept_foreign"] += 1
            continue
        # Reading the PDF is by far the most expensive thing this pipeline does offline — about a
        # second per document, so a corpus-wide re-run is twenty minutes. `import_markdown`'s
        # compare-before-write already made a repeat run write nothing, but only *after* paying
        # that cost, which made `make build` over an unchanged corpus twenty minutes of work for
        # zero output. The provenance record answers the same question up front: its `inputs` are
        # the source hash and the producer, both known here without opening the PDF.
        # A reading this step produced is complete only with its geometry beside it (ADR-042):
        # a `document.md` at the current version whose sidecar is missing is re-read, not skipped.
        if not needs_rebuild(
            store,
            ref,
            artifact="markdown",
            inputs=_reading_inputs(content, language=doc_language, producer=producer),
            present=store.has_markdown(**keys) and store.has_blocks(**keys),
        ):
            counts["skipped_current"] += 1
            continue
        reading = read_document_markdown(content)
        if reading.status == "failed":
            counts["failed"] += 1
            failures.append(
                StepFailure(
                    ref.bill_slug, ref.doc_key, ref.version, reading.error or "reading failed"
                )
            )
            announce(progress, f"[{index}/{len(refs)}] FAILED {ref.bill_slug}/{ref.doc_key}")
            continue
        counts["read"] += 1
        if reading.status == "empty":
            # Nothing is written, and that is `import_markdown`'s call, not this step's: it refuses
            # blank markdown because "an extraction that produced nothing is not a reading of the
            # document", which is right — a file with no text layer yields no content lines at all,
            # so there is not even a page marker to store. Named rather than merely counted, because
            # these are precisely the documents only the cross-check tier can read, and an operator
            # cannot act on the number 12.
            counts["empty"] += 1
            failures.append(
                StepFailure(
                    ref.bill_slug,
                    ref.doc_key,
                    ref.version,
                    NO_TEXT_LAYER,
                )
            )
            announce(progress, f"[{index}/{len(refs)}] {ref.bill_slug}/{ref.doc_key} EMPTY")
            continue
        if reading.suspect:
            counts["suspect"] += 1
        try:
            imported = import_markdown(
                store,
                bill_slug=ref.bill_slug,
                language=doc_language,
                producer=producer,
                doc_key=ref.doc_key,
                version=ref.version,
                markdown_text=reading.markdown,
                blocks=list(reading.blocks),
            )
        except MarkdownImportError as error:
            counts["failed"] += 1
            failures.append(
                StepFailure(ref.bill_slug, ref.doc_key, ref.version, describe_error(error))
            )
            continue
        counts["written" if imported.changed else "unchanged"] += 1
        flag = " SUSPECT" if reading.suspect else ""
        announce(
            progress,
            f"[{index}/{len(refs)}] {ref.bill_slug}/{ref.doc_key} "
            f"{reading.status} {reading.page_count}p{flag}",
        )
    return StepResult(counts=counts, failures=tuple(failures))
