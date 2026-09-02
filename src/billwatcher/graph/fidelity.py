"""Gate P1: does the provision tree account for the markdown it was read from?

Step 4 reads a document's structure with a language model (ADR-022). That is the right tool for the
hardest part of the job — telling an Arrangement of Sections apart from the body it lists — but it
means the canonical Akoma Ntoso for a piece of legislation is a model's output, and a model that
quietly drops clause 7 or renumbers a subsection produces a well-formed document that is wrong.
Publishing that is the worst failure this pipeline has, because nothing downstream can detect it:
the XML parses, the eIds look plausible, and the graph builds.

This gate is the deterministic check between the model and the store. It never asks whether the
reading is *good*; it asks whether it is *accountable* — every provision numbered, numbered once, in
a sequence with no unexplained hole, and covering the words that were on the page.

Six findings, all blocking, and only one of them carries a threshold:

- `duplicate_eid` — two provisions resolving to one identifier. Nothing else catches this:
  `assign_eids` will mint the same eId twice without complaint, and every citation, `hasPart` edge
  and provision IRI beneath it is then ambiguous.
- `missing_num` — a provision with no printed number. `assign_eids` falls back to the parent's eId,
  silently merging two provisions into one identifier.
- `sequence_gap` / `sequence_order` — a skipped or backwards number. Malaysian drafting numbers
  provisions continuously, and the one legitimate irregularity (an inserted `5A` between `5` and
  `6`) is modelled rather than tolerated as slack. A backwards step is the classic
  table-of-contents bleed signature: 1..12, then 1 again.
- `unanchored_run` — a provision run that does not start where the document starts. Comparing
  adjacent numbers is blind to a constant offset, so a tree numbered 3, 4, 5 for a document printed
  1, 2, 3 is continuous by construction while every eId beneath it is wrong.
- `no_source_text` — a tree judged against a source with nothing scoreable in it. There is no basis
  for calling a reading accountable when the coverage check could not run.
- `low_text_coverage` — the one statistical check, and the only one with a threshold.

Coverage is measured over *distinct* words, against the markdown as the extractor was shown it, less
the words that name a structural element. All three choices matter.

Distinct rather than total, because the extractor is instructed to drop Arrangement of Sections
entries and a table-of-contents entry contributes no new distinct word — the body provision it lists
prints the same words. Set coverage is therefore insensitive to how long the Arrangement is, while
still catching what actually matters: a dropped page or a dropped schedule removes whole distinct
words. A multiset ratio over the same text is reported alongside, never blocking, because it is a
useful calibration number and a terrible gate.

Structural keywords are excluded because `BAHAGIAN`, `JADUAL` and `SUSUNAN FASAL` are markup: the
parsers consume them and keep only the number and title, so no faithful tree can ever contain them.
Measured on a short real bill those three words alone cost 5.2% of distinct tokens — enough to fail
a perfectly correct reading — while costing almost nothing on a long one, which would have made the
gate silently stricter for short documents than for long ones. With them excluded a faithful reading
scores exactly 1.0, so the threshold measures what it claims to.

ADR-017's warning is the design constraint here: a gate that fires on almost every document trains
an operator to clear the queue without reading it. Hence one threshold, on the one metric that is
genuinely statistical, configurable because the real corpus is unmeasured (A15).
"""

import html
import re
from dataclasses import dataclass, field
from typing import Any

from billwatcher.graph.tree import Node, body_start, strip_markdown_line
from billwatcher.graph.vocabulary import (
    EID_PREFIXES,
    NODE_LABELS,
    SCHEDULE_ORDINALS,
    alpha_successor,
    back_matter_heading,
    container_heading,
    is_roman,
    provision_number,
    roman_value,
    schedule_heading,
    to_roman,
)

# Types whose document-wide numbering only belongs to a document actually of that unit. A
# clause-numbered bill can still contain "section"-typed nodes -- a quoted or inserted section of
# the Act it amends -- and those sections are numbered by that *other* document, not by this one.
# Found live: a bill quoting sections 31, 44, 49, 50A... of the Act it amends, read as one
# document-wide "section" run and reported as riddled with sequence gaps that were never there.
_UNIT_SCOPED_TYPES = frozenset({"clause", "section"})

# The provision types whose numbering is checked. `preamble` is a node type with no eId prefix and
# no number of its own, and the tree's synthetic `body` root is neither.
NUMBERED_TYPES = frozenset(EID_PREFIXES)

# Types that restart their numbering inside each parent, so continuity is per sibling list.
# `chapter` is here because a Chapter is numbered within its Part — `BAHAGIAN II` opening at
# `Bab 1` is correct drafting, and treating chapters as one document-wide run rejected it. Clauses
# and sections are the exception that motivates the whole distinction: they run continuously across
# Part boundaries even though the parser nests them under the open Part.
RESTARTING_TYPES = frozenset({"chapter", "subsection", "paragraph", "subparagraph"})

# How each type is numbered, which decides how two of its numbers are compared. Malaysian drafting
# numbers Parts and Chapters in roman (`BAHAGIAN I`, `BAHAGIAN II`) and subparagraphs in roman too,
# while paragraphs run through letters (`(a)`, `(b)`) and everything else runs through arabic
# numerals with an optional inserted-provision suffix (`5`, `5A`, `6`).
#
# Keying this on the node type is load-bearing, not tidiness: `I` is simultaneously a valid roman
# numeral and a valid paragraph letter, so a comparison that ignores the type reads `BAHAGIAN I` ->
# `BAHAGIAN II` as a letter sequence, computes the successor of `i` as `j`, and reports a gap on
# every multi-Part bill in the corpus.
_ROMAN_NUMBERED = frozenset({"part", "chapter", "subparagraph"})
_LETTER_NUMBERED = frozenset({"paragraph"})

BLOCKING_FINDINGS = frozenset(
    {
        "duplicate_eid",
        "missing_num",
        "sequence_gap",
        "sequence_order",
        "low_text_coverage",
        "no_source_text",
        "unanchored_run",
    }
)
STATUSES = frozenset({"passed", "mismatch", "empty_tree", "no_source_text", "failed"})

# What a document's first provision may legitimately be numbered. `1` is the norm; a bill whose
# body opens at `2` is a reading that lost its first provision, and one opening at `5` has lost
# four. Kept as a set rather than a bare `== "1"` because an amendment bill occasionally opens at
# `2`, and because a Schedule's own items are checked by the same machinery.
ANCHOR_NUMBERS = frozenset({"1", "2"})

MIN_TEXT_COVERAGE = 0.95

# How many findings a verdict carries into its sidecar. Bounded for the same reason Gate L1 bounds
# its differences: a verdict with ten thousand lines is not read by anybody.
_DETAIL_LIMIT = 50

_TOKEN_RE = re.compile(r"[^0-9a-z]+")

# The line that opens a bill's own text — a bill's provisions cannot precede it, so it is a more
# reliable start-of-body marker than "looks like a heading or a numbered line", which an
# Arrangement of Clauses printed as bare text also satisfies (see `_extractor_view`).
_ENACTING_FORMULA_RE = re.compile(
    r"^(diperbuat\s+oleh\s+parlimen\s+malaysia|enacted\s+by\s+the\s+parliament\s+of\s+malaysia)\b",
    re.IGNORECASE,
)


# MinerU renders a schedule table as literal HTML (`<table><tr><td>...`); replaced with a space
# rather than deleted so two adjacent cells' text does not run together into one fictitious word.
_HTML_TAG_RE = re.compile(r"<[^>]+>")

# A table is one structural unit however MinerU happens to lay out its newlines. Collapsed to one
# line *before* the text is split into lines, so an isolated cell's own text can never be mistaken
# for a standalone heading -- "Huraian" ("particulars") is an entirely ordinary column header, and
# `_BACK_MATTER_HEADING_RE` matches a whole line, not a line's substring.
_TABLE_RE = re.compile(r"<table\b.*?</table>", re.IGNORECASE | re.DOTALL)

# Words that *name* a structural element rather than belonging to a provision's own text:
# `BAHAGIAN`, `JADUAL PERTAMA`, `SUSUNAN FASAL`. Every parser here consumes them and keeps only the
# number and the title, so no node ever stores them — which makes them markup, and charging a
# faithful tree for missing them measures formatting rather than fidelity.
#
# This is not a rounding correction. Measured on a short real bill, these three words alone cost
# 3 of 58 distinct tokens — 5.2%, enough on its own to fail a correct reading at the 0.95 default —
# while on a long document they cost almost nothing. Leaving them in would make the gate quietly
# stricter for short documents than for long ones, which is not a threshold anybody could calibrate.
#
# Derived from the vocabulary rather than restated, so a new structural word cannot be added there
# and forgotten here.
_STRUCTURAL_KEYWORDS = (
    {word.casefold() for label in NODE_LABELS.values() for word in label}
    | {f"{word.casefold()}s" for label in NODE_LABELS.values() for word in label}
    | set(SCHEDULE_ORDINALS)
    | {"susunan", "arrangement"}
)


@dataclass(frozen=True, slots=True)
class Finding:
    kind: str
    eid: str
    expected: str | None = None
    found: str | None = None

    @property
    def is_blocking(self) -> bool:
        return self.kind in BLOCKING_FINDINGS

    def as_detail(self) -> dict[str, Any]:
        detail: dict[str, Any] = {"kind": self.kind, "eid": self.eid}
        if self.expected is not None:
            detail["expected"] = self.expected
        if self.found is not None:
            detail["found"] = self.found
        return detail


@dataclass(frozen=True, slots=True)
class FidelityResult:
    status: str
    unit: str
    node_count: int
    source_tokens: int
    covered_tokens: int
    min_coverage: float
    repeated_token_ratio: float | None = None
    findings: tuple[Finding, ...] = field(default=())
    error: str | None = None

    @property
    def coverage(self) -> float | None:
        """None when there was nothing to cover — reported, never silently scored 1.0."""
        if self.source_tokens == 0:
            return None
        return self.covered_tokens / self.source_tokens

    @property
    def blocking(self) -> tuple[Finding, ...]:
        return tuple(item for item in self.findings if item.is_blocking)

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def as_detail(self) -> dict[str, Any]:
        """The verdict as it is written to `document.structure.gate.json`, pass or fail."""
        detail: dict[str, Any] = {
            "gate": "P1",
            "status": self.status,
            "unit": self.unit,
            "node_count": self.node_count,
            "source_tokens": self.source_tokens,
            "covered_tokens": self.covered_tokens,
            "min_coverage": self.min_coverage,
            "blocking_count": len(self.blocking),
            "findings": [item.as_detail() for item in self.findings[:_DETAIL_LIMIT]],
            "truncated": len(self.findings) > _DETAIL_LIMIT,
        }
        coverage = self.coverage
        if coverage is not None:
            detail["coverage"] = round(coverage, 4)
        if self.repeated_token_ratio is not None:
            detail["repeated_token_ratio"] = round(self.repeated_token_ratio, 4)
        if self.error is not None:
            detail["error"] = self.error
        return detail


def failure(error: str, *, min_coverage: float = MIN_TEXT_COVERAGE) -> FidelityResult:
    """The verdict for a document whose extraction raised before a tree existed."""
    return FidelityResult(
        status="failed",
        unit="",
        node_count=0,
        source_tokens=0,
        covered_tokens=0,
        min_coverage=min_coverage,
        error=error,
    )


def evaluate(
    root: Node, markdown_text: str, *, unit: str, min_coverage: float = MIN_TEXT_COVERAGE
) -> FidelityResult:
    """Judge one provision tree against the markdown it was read from."""
    nodes = list(_walk(root))
    findings: list[Finding] = []
    findings.extend(_duplicate_eids(nodes))
    findings.extend(_missing_nums(nodes))
    findings.extend(_sequence_findings(root, unit=unit))

    source = _tokens(_extractor_view(markdown_text))
    covered = _tokens(" ".join(_tree_text(nodes)))
    source_set = set(source) - _STRUCTURAL_KEYWORDS
    covered_count = len(source_set & set(covered))
    coverage = covered_count / len(source_set) if source_set else None
    if coverage is not None and coverage < min_coverage:
        findings.append(
            Finding(
                kind="low_text_coverage",
                eid="",
                expected=f">={min_coverage:.4f}",
                found=f"{coverage:.4f}",
            )
        )

    if not nodes:
        status = "empty_tree"
    elif not source_set:
        # Nothing scoreable in the source, so coverage was skipped — and a tree cannot be said to
        # account for a document there is no text for. This is what MinerU produces for a scan it
        # recovered nothing from (a file of `<!-- page N -->` markers), and passing it would let an
        # invented tree be published against a document nobody has read.
        status = "no_source_text"
        findings.append(Finding(kind="no_source_text", eid="", found=str(len(nodes))))
    elif any(item.is_blocking for item in findings):
        status = "mismatch"
    else:
        status = "passed"

    return FidelityResult(
        status=status,
        unit=unit,
        node_count=len(nodes),
        source_tokens=len(source_set),
        covered_tokens=covered_count,
        min_coverage=min_coverage,
        repeated_token_ratio=(len(source) / len(source_set)) if source_set else None,
        findings=tuple(findings),
    )


def _walk(root: Node) -> list[Node]:
    """Every numbered descendant in document order. The synthetic `body` root is not one."""
    found: list[Node] = []

    def visit(node: Node) -> None:
        for child in node.children:
            if child.node_type in NUMBERED_TYPES:
                found.append(child)
            visit(child)

    visit(root)
    return found


def _tree_text(nodes: list[Node]) -> list[str]:
    parts: list[str] = []
    for node in nodes:
        if node.num:
            parts.append(node.num)
        if node.heading:
            parts.append(node.heading)
        parts.extend(node.paragraphs)
    return parts


def _extractor_view(markdown_text: str) -> str:
    """The part of the markdown a provision tree is answerable for.

    Three exclusions, all because coverage has to compare like with like.

    Markdown furniture — page-boundary comments, display-math fences, heading punctuation, and (a
    real first-corpus finding) MinerU's HTML table markup — is dropped, so the threshold does not
    end up tracking formatting. Table tags are replaced with a space rather than deleted outright,
    or the text of adjacent cells would run together into one fictitious word; entities such as
    `&quot;`/`&#x27;` are unescaped for the same reason, or their names (`quot`) tokenize as if they
    were content.

    Everything before the document's first structural marker is dropped too, and that one matters
    more than it looks. A real bill PDF opens with a cover page, the long title, the presenter's
    name, the enacting formula and often a whole Arrangement of Sections — none of which a provision
    tree contains, because the parser attaches pre-provision text to the tree's synthetic root and
    the walk skips it. Counting it made a *faithful* reading of a real bill score 0.71-0.81, so the
    0.95 default would have rejected essentially the entire corpus while looking like a strict
    quality bar. Measuring from the first Part, provision or Schedule heading is measuring the thing
    the tree is actually responsible for.

    That "first structural marker" heuristic has a hole a real Arrangement of Clauses falls
    straight through: printed as bare text rather than as a markdown heading, its own listing
    ("1. Tajuk ringkas...", "BAHAGIAN I") satisfies `container_heading`/`provision_number` just as
    readily as the real body's first Part or clause does, so the scan can lock onto the contents
    page instead of skipping it. A bill's own text can never precede its own enacting formula, so
    when that formula is found *after* the first heuristic match, the position right after it is the
    safer start.

    And a bill's back matter — a "HURAIAN" (Explanatory Statement) narrating every clause in prose,
    usually followed by an "IMPLIKASI KEWANGAN" (Financial Implications) note — is standard,
    mandatory content on every printed Malaysian bill (the first real corpus run's dominant finding:
    every one of 181 pilot documents carried a HURAIAN section), and is exactly as untreeable as the
    front matter this function already excludes: it explains the clauses, it is not one of them.
    Measured only from the point the real body is judged to start, so a spurious early "HURAIAN" on
    a committee-stage amendment paper (which reprints the whole bill *after* a short note of its
    own) is not mistaken for the real one.

    The honest cost: front and back matter are now unchecked. That is the right trade, because
    neither was ever checked in any useful sense — no tree can hold either, so their absence is
    indistinguishable from a correct reading. If either ever becomes structured output (an AKN
    `<preface>` beyond the long title, say), it needs its own check rather than a share of this one.
    """
    # Collapsed to one line per table *before* the line split below, so a cell's own text can never
    # be read as a standalone line and mistaken for a heading — see `_TABLE_RE`.
    markdown_text = _TABLE_RE.sub(lambda match: match.group(0).replace("\n", " "), markdown_text)
    lines = [strip_markdown_line(line) for line in markdown_text.splitlines()]
    kept = [line for line in lines if line]

    # No marker anywhere means no front matter was recognised, which is "measure everything" —
    # the same fallback the previous, single-pass version of this function returned.
    # An Arrangement of Clauses is a contents page whose listing satisfies `container_heading` and
    # `provision_number` exactly as the real body does, so neither scan below may be allowed to
    # lock onto it. `body_start` is the same cut the parser makes, which is what keeps this
    # measuring the text the extractor was actually shown rather than an approximation of it.
    floor = body_start(kept)
    start = floor
    for index in range(floor, len(kept)):
        line = kept[index]
        if (
            container_heading(line) is not None
            or schedule_heading(line) is not None
            or provision_number(line) is not None
        ):
            start = index
            break
    for index in range(floor, len(kept)):
        if _ENACTING_FORMULA_RE.match(kept[index]):
            start = max(start, index + 1)
            break

    end = len(kept)
    for index in range(start, len(kept)):
        if back_matter_heading(kept[index]):
            end = index
            break

    text = " ".join(kept[start:end])
    # Tags stripped *before* entities are unescaped, never after: unescaping first would turn an
    # escaped "&lt;" inside a cell's own text into a literal "<", which the tag regex then reads as
    # a real tag opening and consumes everything up to the next real ">" — silently deleting
    # whatever real body text sat in between (found in review, before this ever reached a real
    # document).
    text = _HTML_TAG_RE.sub(" ", text)
    return html.unescape(text)


def tokens_for_comparison(markdown_text: str) -> list[str]:
    """The tokens two *independent readings* of one document should share (ADR-035).

    Gate P1's own tokenisation, so a divergence number and a coverage number mean comparable
    things — but taken over the whole reading rather than `_extractor_view`'s body slice. That
    slice is deliberately not reused here: its start is found by scanning for the first structural
    marker, and two readings of one page can legitimately locate that marker at different offsets,
    so a divergence measured on it would partly be measuring disagreement about where the body
    begins rather than about the text itself.

    Markdown furniture goes: page markers and marginal notes are HTML comments, which `_HTML_TAG_RE`
    consumes along with table markup, and none of it is something two different producers were ever
    going to render identically.
    """
    text = _HTML_TAG_RE.sub(" ", markdown_text)
    return _tokens(html.unescape(text))


def _tokens(text: str) -> list[str]:
    return [token for token in _TOKEN_RE.split(text.casefold()) if token]


def _duplicate_eids(nodes: list[Node]) -> list[Finding]:
    counts: dict[str, int] = {}
    for node in nodes:
        if node.eid:
            counts[node.eid] = counts.get(node.eid, 0) + 1
    return [
        Finding(kind="duplicate_eid", eid=eid, found=str(count))
        for eid, count in sorted(counts.items())
        if count > 1
    ]


def _missing_nums(nodes: list[Node]) -> list[Finding]:
    return [
        Finding(kind="missing_num", eid=node.eid or f"<{node.node_type}>")
        for node in nodes
        if not node.num
    ]


def _sequence_findings(root: Node, *, unit: str) -> list[Finding]:
    """Continuity, at the scope each provision type actually uses.

    Scope is the trap here. Clauses do not restart inside a Part, but the parser nests them under
    the open Part, so checking every sibling list would demand that Part II's first clause be
    numbered 1 and would fire on almost every multi-Part bill. Provisions are therefore one
    document-wide sequence; the types in `RESTARTING_TYPES` restart per parent.

    A document-wide run has to be assembled in *document* order, which is depth-first: a tree where
    the same provision type sits at more than one depth — some clauses under a Part, some directly
    under the body, which is what a document with an unheaded opening section looks like — would
    otherwise be collected level by level and compared out of order, reporting gaps and backwards
    steps that are not in the document at all.

    A `clause`/`section` node whose type does not match `unit`, *nested inside a provision of the
    document's own unit*, is a different case again: this document is a bill (or an Act), and a
    node typed the other way sitting inside one of its own clauses (or sections) is a fragment
    quoted from whatever it amends — some other Act's section 50A, say, spliced into this bill's
    clause 6. That fragment's own numbering belongs to the document it was quoted from, not to this
    one, so it is read (its children still restart-checked normally) but left out of the
    document-wide run entirely, rather than being compared against clauses or sections it has
    nothing to do with.

    That exclusion is conditional on nesting, not on type alone — a mismatched-type node found
    *before* the document-wide run ever reaches its own unit (at the top level, or nested only
    under Parts/Chapters) is not a quotation, it is the extractor's own reading of the document's
    real provisions typed wrong, and skipping it would silently defeat the very thing this gate
    exists to catch (a model that drops or mistypes a clause produces a well-formed tree that is
    wrong). `inside_unit` is only ever set once the walk has actually entered a node of the
    document's own unit, so a genuine quotation nested inside one is excluded and a top-level
    mistyping is not.
    """
    findings: list[Finding] = []
    document_wide: dict[str, list[Node]] = {}

    def collect(node: Node, *, inside_unit: bool) -> None:
        siblings: dict[str, list[Node]] = {}
        for child in node.children:
            if child.node_type not in NUMBERED_TYPES:
                continue
            if child.node_type in RESTARTING_TYPES:
                siblings.setdefault(child.node_type, []).append(child)
            elif inside_unit and child.node_type in _UNIT_SCOPED_TYPES and child.node_type != unit:
                pass
            else:
                document_wide.setdefault(child.node_type, []).append(child)
            collect(child, inside_unit=inside_unit or child.node_type == unit)
        for group in siblings.values():
            findings.extend(_check_run(group))

    collect(root, inside_unit=False)
    for node_type in sorted(document_wide):
        run = document_wide[node_type]
        findings.extend(_check_run(run))
        if node_type == unit:
            findings.extend(_anchor_finding(run))
    return findings


def _anchor_finding(run: list[Node]) -> list[Finding]:
    """Check where a document's provision run *starts*, not only that it is continuous.

    Adjacent-pair checking is blind to a constant offset: a tree numbered 3, 4, 5 for a document
    printed 1, 2, 3 is continuous by construction and set coverage barely moves, because the
    provision *text* is all still there and only the numbers are wrong. Every eId, every provision
    IRI and every citation in that document is then off by two, which is exactly the class of
    well-formed-but-wrong reading this gate exists to stop. The first number is the one anchor the
    document itself supplies.
    """
    first = next((node for node in run if node.num), None)
    if first is None or first.num in ANCHOR_NUMBERS:
        return []
    return [
        Finding(
            kind="unanchored_run",
            eid=first.eid,
            expected=f"one of {sorted(ANCHOR_NUMBERS)}",
            found=first.num,
        )
    ]


def _check_run(nodes: list[Node]) -> list[Finding]:
    findings: list[Finding] = []
    previous: Node | None = None
    for node in nodes:
        if node.num and previous is not None and previous.num:
            findings.extend(_compare(previous, node))
        if node.num:
            previous = node
    return findings


def _compare(previous: Node, node: Node) -> list[Finding]:
    prev_num, cur_num = previous.num or "", node.num or ""
    if (
        node.node_type in _ROMAN_NUMBERED
        and prev_num.isalpha()
        and cur_num.isalpha()
        and alpha_successor(prev_num).casefold() == cur_num.casefold()
    ):
        # `C` -> `D` is a genuine next-letter step, but `is_roman` accepts both of them too (100,
        # 500) — Malaysian drafting nests `subparagraph` at both a roman-numbered depth (`i`, `ii`)
        # and a plain lettered one (`A`, `B`, `C`...), and the node type alone cannot tell which a
        # given run is. Found live: a real `A, B, C, D` run read as a jump from 100 to 500 and
        # rejected as a "sequence_gap" expecting `CI`. Real drafting never mixes the two
        # conventions within one run, so if the letter reading says this pair is exactly
        # consecutive, that is the reading — the roman one below is reached only when it is not.
        return []
    expected = _successor(prev_num, node.node_type)
    if expected is None:
        return []
    order = _order(prev_num, cur_num, node.node_type)
    if order is not None and order <= 0:
        return [
            Finding(
                kind="sequence_order",
                eid=node.eid,
                expected=f"after {previous.num}",
                found=node.num,
            )
        ]
    if node.num != expected and order is not None and order > 1:
        return [Finding(kind="sequence_gap", eid=node.eid, expected=expected, found=node.num)]
    return []


def _successor(num: str, node_type: str) -> str | None:
    """The number that should follow `num`, or None when the token's kind is not modelled.

    Returning None means "no opinion", and no finding is emitted. That is the right default for an
    unrecognised token: a gate that guesses at a numbering scheme it does not understand reports a
    gap that is not there, which is precisely the ADR-017 failure this module exists to avoid.
    """
    if node_type in _ROMAN_NUMBERED and is_roman(num):
        successor = to_roman(roman_value(num) + 1)
        # Match the case the document printed, so an operator reading the verdict sees the token
        # they would search the page for.
        return successor.upper() if num.isupper() else successor
    if num.isdigit():
        return str(int(num) + 1)
    if node_type in _LETTER_NUMBERED and num.isalpha():
        return alpha_successor(num)
    return None


def _order(previous: str, current: str, node_type: str) -> int | None:
    """How far `current` is after `previous`, or None when the two are not comparable.

    `5` -> `5A` is 0 distance in the integer part but is a legitimate insertion, not a repeat, so
    the alphabetic suffix breaks the tie the way `structure._sort_key` already does for Gate L1.
    """
    if node_type in _ROMAN_NUMBERED and is_roman(previous) and is_roman(current):
        return roman_value(current) - roman_value(previous)
    left, right = _numeric_key(previous), _numeric_key(current)
    if left is not None and right is not None:
        if left[0] != right[0]:
            return right[0] - left[0]
        return 1 if right[1] > left[1] else (0 if right[1] == left[1] else -1)
    if node_type in _LETTER_NUMBERED and previous.isalpha() and current.isalpha():
        return _alpha_distance(previous, current)
    return None


def _numeric_key(num: str) -> tuple[int, str] | None:
    match = re.fullmatch(r"(\d+)([A-Za-z]*)", num)
    if not match:
        return None
    return int(match.group(1)), match.group(2).casefold()


def _alpha_distance(previous: str, current: str) -> int | None:
    """Positions between two paragraph letters, or None when the walk does not reach the target.

    None rather than a guess: the sequence is walked forwards, so a target it never reaches is a
    token this function cannot place, and inventing a distance for it would fabricate a gap.
    """
    token, steps = previous.casefold(), 0
    target = current.casefold()
    while steps < 64:
        if token == target:
            return steps
        token = alpha_successor(token)
        steps += 1
    return -1 if target < previous.casefold() else None
