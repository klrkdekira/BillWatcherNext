"""Structure extraction without a vLLM endpoint: emit a work packet, read the answer back.

The Akoma Ntoso step was the one place in this pipeline that *required* a model. Markdown had two
model-free routes already — the local geometric reading (ADR-035) and `import-markdown` for a
reading produced anywhere else (ADR-021) — but the structure extraction had exactly one
implementation, gated on the operator having a vLLM endpoint at all, so one without an endpoint —
or one who would rather
have a coding agent read a difficult bill by hand — had no way in at all.

This module closes that. `write_handoff` writes one self-contained packet per document — the
markdown, and an instruction naming precisely the JSON that must come back —  and
`FileStructureExtractor` reads those answers and feeds them through the *same* `convert_to_akn`
path as the vLLM extractor: same eId assignment, same Gate P1, same provenance shape. An
agent-produced reading is therefore judged exactly as strictly as a model-produced one, and is
distinguishable from it in the record rather than blended into it.

Answers are matched to documents by the **hash of the markdown they were read from**, never by
filename or position. The protocol `convert_to_akn` calls has no document identity in it
(`extract(markdown_text, *, unit)`), and hashing is better than widening it: an answer written
against a different document's text cannot be silently attached to this one.
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from billwatcher.download.documents import VERSION as DOCUMENT_VERSION
from billwatcher.graph.structure import Node, StructureUnavailable, infer_language_and_unit
from billwatcher.graph.vocabulary import NODE_LABELS, NODE_TYPES
from billwatcher.reporting import (
    Progress,
    StepFailure,
    StepResult,
    announce,
    describe_error,
)
from billwatcher.store import PipelineStore, keys_for

# --- the structure contract ------------------------------------------------------------
# Moved here verbatim from the vLLM extractor when that path was dropped: the instruction and
# the JSON shape it asks for are now read by whatever fills in a packet — a coding agent, a
# person, or a model an operator drives themselves — and `AnswerNode` is both the single statement
# of the shape they must return and the single place an answer becomes a `Node`, so every reading
# is parsed and defended against identically.

_VOCABULARY_LINES = "\n".join(
    f"- {node_type}: {NODE_LABELS[node_type][0]} (Malay) / {NODE_LABELS[node_type][1]} (English)"
    for node_type in sorted(NODE_TYPES)
)

SYSTEM_PROMPT = f"""You are a legislative document structure extractor for Malaysian Parliament \
bills. You read markdown text produced from a bill PDF and output ONLY a JSON object describing \
the document's provision hierarchy - no prose, no markdown code fences, no commentary.

Structural vocabulary (Malay / English), one node type per kind of provision:
{_VOCABULARY_LINES}

Rules:
- Malaysian bills use Fasal (clause); enacted Acts use Seksyen (section). Use whichever the \
document's own text uses; default to "clause" if genuinely ambiguous.
- If the markdown includes an Arrangement of Sections/Clauses - a table of contents near the \
front of the document, headed "Susunan Seksyen", "Susunan Fasal", "Arrangement of Sections", or \
"Arrangement of Clauses" - do not emit nodes for those table-of-contents entries. Emit nodes only \
for the real body provisions that follow, with their actual text.
- A schedule ("Jadual" / "Schedule") restarts its own numbering: its numbered items are \
"paragraph" nodes of the schedule, never new top-level provisions.
- "num" is the bare token only, with no surrounding punctuation the typesetting added: strip a \
trailing period ("5." is "5"; "5A." is "5A") and strip enclosing parentheses ("(1)" is "1"; \
"(a)" is "a"; "(bb)" is "bb"; "(iv)" is "iv"). Never include the parentheses or the period in \
"num" itself.
- Do not invent an eId, an identifier, or a citation of any kind - that is computed separately \
from what you return.
- Output strictly this JSON shape and no other top-level keys:
  {{"children": [
    {{"node_type": "part|chapter|section|clause|subsection|paragraph|subparagraph|schedule",
      "num": "5A" or null, "heading": "..." or null,
      "paragraphs": ["body text, one string per paragraph"],
      "children": [ ... same shape, nested ... ]}}
  ]}}
"""


# The prompt's own identity. A prompt change is a change in how every document was read, so it
# belongs in each artifact's provenance — hashing the constant means the record cannot drift from
# the prompt actually sent, the way a hand-maintained version string would.
PROMPT_SHA256 = hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()


def _normalize_num(num: object) -> str | None:
    """Strip punctuation the prompt asks the model not to include, defensively.

    A model that emits "(1)" or "5." despite the instruction would otherwise poison every eId
    beneath that node with literal parentheses or a stray period (found live: the model's first
    response over this exact prompt did exactly that for every parenthesised token). A real
    Malaysian Supply Bill's vote numbers ("B. 1", "B. 10" — letter, dot, space, digit) do the same
    with embedded whitespace: an eId may never contain whitespace, so a survivor here does not fail
    the reading, it fails the *schema*, turning a document Gate P1 would have judged normally into
    an opaque validator crash (found live).
    """
    if num is None:
        return None
    text = str(num).strip()
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1]
    text = "".join(text.split())
    return text.removesuffix(".") or None


class AnswerNode(BaseModel):
    """One node of an answer, as the instruction asks for it and before it becomes a `Node`.

    A model rather than a hand-written `dict[str, Any]` reader because the writer is *outside* this
    codebase — a coding agent, a person, or a model an operator drives themselves — so this is the
    one place in the pipeline where mypy's strictness buys nothing and the shape has to be checked
    at runtime. Validating declaratively means every defect in a packet is reported with the path
    that produced it (`children.3.children.0.num`) instead of surfacing as a `KeyError` somewhere
    down in tree assembly.

    `extra="forbid"` enforces the instruction's own "no other top-level keys" rule, and is the
    point rather than pedantry: a writer that answers with `"text"` where the contract says
    `"paragraphs"` silently produced an *empty* provision under the old reader, which is a defect
    the fidelity gate can only catch by coverage, after the fact and without naming the cause.
    """

    model_config = ConfigDict(extra="forbid")

    node_type: str
    num: str | None = None
    heading: str | None = None
    paragraphs: list[str] = Field(default_factory=list)
    children: list["AnswerNode"] = Field(default_factory=list)

    @field_validator("node_type")
    @classmethod
    def _known_node_type(cls, value: str) -> str:
        if value not in NODE_TYPES:
            raise ValueError(f"unknown node_type: {value!r}")
        return value

    @field_validator("num", "heading", "paragraphs", mode="before")
    @classmethod
    def _as_text(cls, value: object) -> object:
        """Coerce what a writer emitted to the text the tree is built from.

        A number left unquoted (`"num": 5`) is the common case and was tolerated before, so it stays
        tolerated: refusing it would reject an otherwise faithful reading over JSON typing, which is
        not what the gate is meant to judge. `None` passes through as the absent value it means.
        """
        if value is None:
            return None
        if isinstance(value, list):
            return [item if item is None else str(item) for item in value]
        return str(value)

    @field_validator("num")
    @classmethod
    def _normalized_num(cls, value: str | None) -> str | None:
        return _normalize_num(value)

    @model_validator(mode="after")
    def _default_schedule_num(self) -> "AnswerNode":
        if self.num is None and self.node_type == "schedule":
            # A document with one schedule does not number it, so a faithful reading of a bare
            # `JADUAL` has no number to report. The regex parser already applies the convention that
            # such a schedule is schedule 1 (`vocabulary.schedule_heading`); applying it here too
            # means the correct reading is not rejected by the gate's `missing_num` check for being
            # correct.
            self.num = "1"
        return self

    def to_node(self) -> Node:
        """The validated answer as the tree `assign_eids` and `render_akn` operate on."""
        return Node(
            node_type=self.node_type,
            num=self.num,
            heading=self.heading,
            eid="",
            paragraphs=list(self.paragraphs),
            children=[child.to_node() for child in self.children],
        )


class StructureAnswer(BaseModel):
    """A whole `structure.json`: the top-level nodes of one document's provision hierarchy."""

    model_config = ConfigDict(extra="forbid")

    children: list[AnswerNode] = Field(default_factory=list)

    def to_body(self) -> Node:
        """A `body` root with these nodes under it, exactly as the vLLM extractor built it.

        The tree handed to `assign_eids` must have the same shape whichever extractor produced it,
        or eIds would differ between the two paths for identical structure.
        """
        root = Node(node_type="body", num=None, heading=None, eid="")
        root.children = [child.to_node() for child in self.children]
        return root


# The filenames one packet is made of. `document.md` is a copy rather than a reference so the packet
# is self-contained: an agent can be pointed at this directory and needs no access to the store, no
# knowledge of its layout, and no ability to resolve a doc-key back to a document.
MARKDOWN_FILENAME = "document.md"
INSTRUCTION_FILENAME = "INSTRUCTION.md"
ANSWER_FILENAME = "structure.json"
MANIFEST_FILENAME = "manifest.json"

EXTRACTOR_NAME = "handoff-file"


class HandoffError(RuntimeError):
    """A handoff tree cannot be read, or an answer in it is not usable."""


def _digest(markdown_text: str) -> str:
    return hashlib.sha256(markdown_text.encode("utf-8")).hexdigest()


def write_handoff(
    store: PipelineStore,
    *,
    root: Path,
    progress: Progress = None,
    overwrite_answers: bool = False,
) -> StepResult:
    """Write one packet per document that has a markdown reading, under `root`.

    A packet whose `structure.json` already exists is left alone unless `overwrite_answers`: the
    answer is the expensive part — someone's or something's actual reading of a bill — and a
    re-emitted handoff must not delete it.
    """
    counts = {"documents": 0, "written": 0, "answered": 0, "no_reading": 0, "failed": 0}
    failures: list[StepFailure] = []
    entries: list[dict[str, Any]] = []
    refs = [ref for ref in store.iter_documents() if ref.version == DOCUMENT_VERSION]
    announce(progress, f"{len(refs)} stored document(s) to consider for handoff")

    for ref in refs:
        counts["documents"] += 1
        keys = keys_for(ref)
        markdown = store.load_markdown(**keys)
        if not markdown:
            counts["no_reading"] += 1
            continue
        _, unit = infer_language_and_unit(markdown)
        directory = root / ref.bill_slug / ref.doc_key / f"v{ref.version:03d}"
        answer = directory / ANSWER_FILENAME
        already_answered = answer.exists()
        if already_answered and not overwrite_answers:
            counts["answered"] += 1
        try:
            directory.mkdir(parents=True, exist_ok=True)
            (directory / MARKDOWN_FILENAME).write_text(markdown, encoding="utf-8")
            (directory / INSTRUCTION_FILENAME).write_text(
                _instruction(ref.bill_slug, ref.doc_key, ref.version, unit=unit),
                encoding="utf-8",
            )
            if already_answered and overwrite_answers:
                answer.unlink()
        except OSError as error:
            counts["failed"] += 1
            failures.append(
                StepFailure(ref.bill_slug, ref.doc_key, ref.version, describe_error(error))
            )
            continue
        counts["written"] += 1
        entries.append(
            {
                "bill_slug": ref.bill_slug,
                "doc_key": ref.doc_key,
                "version": ref.version,
                "unit": unit,
                "markdown_sha256": _digest(markdown),
                "answer": str(
                    Path(ref.bill_slug) / ref.doc_key / f"v{ref.version:03d}" / ANSWER_FILENAME
                ),
                "answered": already_answered and not overwrite_answers,
            }
        )
    root.mkdir(parents=True, exist_ok=True)
    (root / MANIFEST_FILENAME).write_text(
        json.dumps({"packets": entries}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return StepResult(counts=counts, failures=tuple(failures))


def _instruction(bill_slug: str, doc_key: str, version: int, *, unit: str) -> str:
    """One packet's task, written to be actionable with no other context.

    The extraction rules are `SYSTEM_PROMPT` itself, not a paraphrase of it: two producers reading
    the same corpus to different rules would put two incompatible structural conventions into one
    dataset, and a paraphrase is how that happens without anybody deciding it.
    """
    return f"""# Extract the provision structure of {bill_slug}/{doc_key}/v{version:03d}

Read `{MARKDOWN_FILENAME}` in this directory and write `{ANSWER_FILENAME}` beside it.

- The document's unit is **{unit}** (inferred from its own Arrangement heading).
- `{ANSWER_FILENAME}` must be the JSON object described below and nothing else: no prose, no
  markdown fences, no commentary.
- Do not edit `{MARKDOWN_FILENAME}`. It is the text your answer is matched against, by hash — an
  answer written against altered text will be refused rather than misattributed.
- An answer you are not confident in is worse than no answer. Leaving `{ANSWER_FILENAME}` absent
  reports this document as unconverted; a wrong structure may pass the fidelity gate and be
  published. Skip rather than guess.

## The rules your answer must follow

{SYSTEM_PROMPT}
"""


@dataclass
class FileStructureExtractor:
    """A `MarkdownStructureExtractor` backed by answers in a handoff tree.

    Satisfies the same protocol the vLLM extractor does, so `convert_to_akn` neither knows nor
    cares which produced a reading — while `name` and `model_id` keep the two apart in provenance,
    which is what stops an agent-produced tree from reading as a model-produced one after the fact
    (ADR-026 staleness is computed from exactly these fields).
    """

    root: Path
    model_id: str | None = None
    name: str = EXTRACTOR_NAME
    # Declared `str | None` to match the protocol exactly: a Protocol's attribute types are
    # invariant, so narrowing it here makes this class fail to satisfy `MarkdownStructureExtractor`.
    prompt_sha256: str | None = hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()
    answers: dict[str, StructureAnswer] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.answers:
            self.answers = load_answers(self.root)

    def extract(self, markdown_text: str, *, unit: str) -> Node:
        payload = self.answers.get(_digest(markdown_text))
        if payload is None:
            # `StructureUnavailable`, not an error: a handoff corpus is answered incrementally, so
            # "no answer yet" is the ordinary state of most packets on most runs. A stale answer —
            # one whose `document.md` was edited after it was written — lands here too and is
            # indistinguishable from unanswered, which is the safe direction: it errs toward not
            # converting, never toward attaching a reading to text it was not read from.
            raise StructureUnavailable(
                "no structure.json in the handoff tree matches this document's markdown"
            )
        # Already validated by `load_answers`, so nothing here can fail on a malformed answer: a
        # packet that does not match the contract was refused by name and path before the run began,
        # rather than becoming one anonymous "failed" document in the middle of it.
        return payload.to_body()


def load_answers(root: Path) -> dict[str, StructureAnswer]:
    """Every usable answer in a handoff tree, keyed by the markdown digest it was written against.

    Keyed by re-hashing the packet's own `document.md` rather than trusting the manifest, so an
    answer follows the text it was actually read from even if the manifest is stale or absent.
    """
    if not root.is_dir():
        raise HandoffError(f"not a handoff directory: {root}")
    answers: dict[str, StructureAnswer] = {}
    for answer_path in sorted(root.glob(f"*/*/v*/{ANSWER_FILENAME}")):
        markdown_path = answer_path.with_name(MARKDOWN_FILENAME)
        if not markdown_path.exists():
            continue
        # Parsed and validated in two steps, not by `model_validate_json`, to keep the two
        # failures distinguishable in the report: "your file is not JSON" and "your JSON is not an
        # answer" are different things for whoever has to fix the packet.
        try:
            raw = json.loads(answer_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise HandoffError(f"{answer_path} is not readable JSON: {error}") from None
        try:
            payload = StructureAnswer.model_validate(raw)
        except ValidationError as error:
            # Loud and fatal, matching how an unparseable answer has always been treated, and for
            # the same reason: a packet that does not meet the contract is damage in a tree the
            # operator controls, and conversion is hours of work to spend on a corpus one document
            # of which is already known to be wrong. Reported here, at load, so the message can name
            # the file — at `extract` time answers are keyed by digest and the path is gone.
            raise HandoffError(
                f"{answer_path} does not match the answer contract: {error}"
            ) from None
        answers[_digest(markdown_path.read_text(encoding="utf-8"))] = payload
    return answers
