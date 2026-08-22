"""The vLLM-assisted markdown structure extractor for the Akoma Ntoso conversion step.

Sends a document's markdown to a configured OpenAI-compatible chat-completions endpoint and asks
for its provision hierarchy back as JSON — the same class of endpoint this project already uses
for RAG answers, called the same way (a system prompt, one user message, plain `httpx`, no vendor
SDK). What the model returns is *structure only*: node types, printed numbers, headings, and body
text. It never assigns an eId — `pipeline.akn.assign_eids` does that deterministically from the
model's `node_type`/`num` output, the same way HANDOFF 26.2 forbids guessing a `wId` from
anything but a provision's own printed identity.
"""

import hashlib
import json
from typing import Any

import httpx

from billwatcher.config import Settings
from billwatcher.legislation.vocabulary import NODE_LABELS, NODE_TYPES
from billwatcher.pipeline.akn import Node

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


class StructureExtractorUnavailable(RuntimeError):
    """The configured vLLM endpoint could not read this document's structure."""


class VllmMarkdownStructureExtractor:
    """Calls a vLLM (or other OpenAI-compatible) chat-completions endpoint for the structure."""

    name = "vllm"
    prompt_sha256: str | None = PROMPT_SHA256

    def __init__(
        self,
        *,
        model_id: str,
        base_url: str,
        api_key: str = "",
        timeout_seconds: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model_id: str | None = model_id
        self.endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def extract(self, markdown_text: str, *, unit: str) -> Node:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        user_prompt = (
            f"The document type suggests unit={unit!r} if the text itself is ambiguous.\n\n"
            f"Markdown:\n{markdown_text}"
        )
        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self.transport) as client:
                response = client.post(
                    self.endpoint,
                    headers=headers,
                    json={
                        "model": self.model_id,
                        "temperature": 0,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        "response_format": {"type": "json_object"},
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise StructureExtractorUnavailable(
                f"vLLM structure request failed: {type(error).__name__}"
            ) from error

        try:
            content = payload["choices"][0]["message"]["content"]
            data = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise StructureExtractorUnavailable(
                "vLLM returned a response that was not the expected JSON"
            ) from error

        root = Node(node_type="body", num=None, heading=None, eid="")
        try:
            root.children = [_node_from_dict(child) for child in data.get("children") or []]
        except (KeyError, TypeError, ValueError) as error:
            raise StructureExtractorUnavailable(
                f"vLLM response did not match the expected shape: {error}"
            ) from error
        return root


def _normalize_num(num: object) -> str | None:
    """Strip punctuation the prompt asks the model not to include, defensively.

    A model that emits "(1)" or "5." despite the instruction would otherwise poison every eId
    beneath that node with literal parentheses or a stray period (found live: the model's first
    response over this exact prompt did exactly that for every parenthesised token).
    """
    if num is None:
        return None
    text = str(num).strip()
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1]
    return text.removesuffix(".") or None


def _node_from_dict(data: dict[str, Any]) -> Node:
    node_type = data["node_type"]
    if node_type not in NODE_TYPES:
        raise ValueError(f"unknown node_type in vLLM response: {node_type!r}")
    num = _normalize_num(data.get("num"))
    if num is None and node_type == "schedule":
        # A document with one schedule does not number it, so a faithful reading of a bare `JADUAL`
        # has no number to report. The regex parser already applies the convention that such a
        # schedule is schedule 1 (`vocabulary.schedule_heading`); applying it here too means the
        # correct reading is not rejected by the gate's `missing_num` check for being correct.
        num = "1"
    node = Node(
        node_type=node_type,
        num=num,
        heading=data.get("heading"),
        eid="",
        paragraphs=[str(item) for item in (data.get("paragraphs") or [])],
    )
    node.children = [_node_from_dict(child) for child in data.get("children") or []]
    return node


def build_structure_extractor(settings: Settings) -> VllmMarkdownStructureExtractor:
    """Resolve the configured vLLM endpoint, refusing to invent a default.

    There is no silent fallback to `RegexMarkdownStructureExtractor` here: that extractor exists
    for tests and explicit offline use, not as a production default a missing setting quietly
    activates.
    """
    if not (settings.akn_llm_enabled and settings.akn_llm_base_url and settings.akn_llm_model_id):
        raise StructureExtractorUnavailable(
            "no AKN structure extractor is configured; set AKN_LLM_ENABLED=true, "
            "AKN_LLM_BASE_URL and AKN_LLM_MODEL_ID"
        )
    return VllmMarkdownStructureExtractor(
        model_id=settings.akn_llm_model_id,
        base_url=settings.akn_llm_base_url,
        api_key=settings.akn_llm_api_key,
        timeout_seconds=settings.akn_llm_timeout_seconds,
    )
