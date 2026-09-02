"""Datastar server-sent event encoding.

Datastar patches the DOM from `text/event-stream` events. The wire format is line-oriented:
every event line is prefixed with `data: `, multi-line payloads repeat the prefix, and an event
is terminated by a blank line. Getting that wrong fails silently in the browser, so the encoding
lives here behind one tested function rather than being formatted inline at each call site.

Reference: https://data-star.dev/reference/sse_events
"""

from collections.abc import Iterable

PATCH_ELEMENTS = "datastar-patch-elements"
PATCH_SIGNALS = "datastar-patch-signals"

# Patch modes Datastar understands. `outer` replaces the matched element, which is what a
# fragment that re-renders a whole region wants.
MODES = frozenset({"outer", "inner", "replace", "prepend", "append", "before", "after", "remove"})

SSE_HEADERS = {
    "Cache-Control": "no-store",
    # Proxies that buffer a stream defeat the point of streaming it.
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def _data_lines(field: str, value: str) -> Iterable[str]:
    """Emit one `data: <field> <line>` per line, which is how multi-line payloads are carried."""
    for line in value.splitlines() or [""]:
        yield f"data: {field} {line}\n"


def patch_elements(
    elements: str,
    *,
    selector: str | None = None,
    mode: str = "outer",
    use_view_transition: bool = False,
) -> str:
    """Encode one element patch. Without a selector, Datastar matches on the element's own id."""
    if mode not in MODES:
        raise ValueError(f"unknown patch mode: {mode!r}")
    parts = [f"event: {PATCH_ELEMENTS}\n"]
    if selector:
        parts.append(f"data: selector {selector}\n")
    if mode != "outer":
        parts.append(f"data: mode {mode}\n")
    if use_view_transition:
        parts.append("data: useViewTransition true\n")
    parts.extend(_data_lines("elements", elements.strip()))
    parts.append("\n")
    return "".join(parts)


def patch_signals(signals: str, *, only_if_missing: bool = False) -> str:
    """Encode one signal patch. `signals` must already be a JSON object literal."""
    parts = [f"event: {PATCH_SIGNALS}\n"]
    if only_if_missing:
        parts.append("data: onlyIfMissing true\n")
    parts.extend(_data_lines("signals", signals))
    parts.append("\n")
    return "".join(parts)


def comment(text: str) -> str:
    """A keep-alive comment. Ignored by the client, but keeps an idle connection from timing out."""
    return f": {text}\n\n"
