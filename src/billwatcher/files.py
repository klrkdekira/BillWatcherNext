"""Writing a file so that a reader never sees a half-written one.

Every artifact this pipeline produces is a file, and every step is resumable, which makes these
two primitives load-bearing rather than incidental. `write_atomically` is what lets an
existence-only check ("is there a markdown reading for this document?") be trusted after a crash;
`sidecar_bytes` is what lets a re-run of a step that changed nothing write nothing, because the
bytes of an unchanged sidecar are identical rather than merely equivalent.

Extracted from the audit tree of the Postgres-backed system (now under `legacy/`), where the same
two guarantees were what made a rebuild provably a no-op over an already-correct tree.
"""

import json
import os
from pathlib import Path
from typing import Any

# Bumped when the *shape* of a sidecar changes, so a reader can tell an old sidecar from a new one
# rather than guessing from which keys happen to be present.
METADATA_SCHEMA_VERSION = 1


def write_atomically(path: Path, payload: bytes) -> None:
    """Replace `path`'s contents with `payload` in one indivisible step.

    A plain `write_bytes` truncates first and writes second, so a crash between the two leaves a
    short file that still exists — and an existence-only check (`has_document`, `has_akn`) then
    calls it done forever. Writing a sibling and renaming it means a reader either sees the whole
    previous file or the whole new one; `os.replace` is atomic within a filesystem.

    The temp name is dotted so it matches none of the readers' globs (`body.*`, `metadata.json`,
    `document.*`) and so a leftover from a killed process cannot be mistaken for an artifact by
    `verify`, which reports every unexpected file it finds.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    try:
        with temp.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def sidecar_bytes(data: dict[str, Any]) -> bytes:
    """Serialise a sidecar deterministically: sorted keys, two-space indent, UTF-8, LF.

    Determinism here is what makes a re-run of an unchanged step write nothing at all: the
    comparison downstream is on bytes, so a dict that serialises two ways would look like a change
    on every run and churn both the store and the published tree.
    """
    text = json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False)
    return (text + "\n").encode("utf-8")
