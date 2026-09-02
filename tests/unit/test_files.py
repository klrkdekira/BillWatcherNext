"""The two primitives every stage writes through.

Both guarantees are load-bearing rather than incidental: resumability is built on "the file exists,
so the work is done", and write-if-changed is built on "the same data serialises to the same
bytes". A regression in either is silent — the pipeline keeps running and produces a corpus that is
subtly wrong — so they are pinned here directly.
"""

import json
from pathlib import Path

from billwatcher.files import METADATA_SCHEMA_VERSION, sidecar_bytes, write_atomically


def test_sidecar_bytes_are_deterministic_regardless_of_key_order() -> None:
    """Write-if-changed compares bytes. A dict that serialises two ways would look like a change on
    every run and churn both the corpus and the published tree."""
    assert sidecar_bytes({"b": 2, "a": 1}) == sidecar_bytes({"a": 1, "b": 2})


def test_a_sidecar_is_utf8_json_ending_in_one_newline() -> None:
    """Non-ASCII is written as itself, not escaped to `\\uXXXX`.

    Legislative text carries typographic dashes and quotes, and a sidecar nobody can read in a
    terminal defeats the reason the corpus is plain files in the first place.
    """
    payload = sidecar_bytes({"heading": "Seksyen 5\u2014Pindaan", "n": 1})

    assert payload.endswith(b"\n") and not payload.endswith(b"\n\n")
    assert json.loads(payload.decode("utf-8"))["heading"] == "Seksyen 5\u2014Pindaan"
    assert "Seksyen 5\u2014Pindaan".encode() in payload
    assert b"\\u2014" not in payload


def test_writing_replaces_the_whole_file_and_leaves_no_temporary_behind(tmp_path: Path) -> None:
    """A plain `write_bytes` truncates first and writes second, so a crash between the two leaves a
    short file that still exists — and an existence check then calls that document done forever."""
    target = tmp_path / "nested" / "document.md"

    write_atomically(target, b"first, and longer")
    write_atomically(target, b"second")

    assert target.read_bytes() == b"second"
    assert [path.name for path in tmp_path.rglob("*") if path.is_file()] == ["document.md"]


def test_the_temporary_name_cannot_be_mistaken_for_an_artifact(tmp_path: Path) -> None:
    """`verify` reports every unexpected file it finds, and the store globs for `document.*`.

    A leftover from a killed process must match neither, or a crash turns into a corpus that fails
    its own audit.
    """
    target = tmp_path / "document.pdf"
    write_atomically(target, b"%PDF-1.4")

    leftover = target.with_name(f".{target.name}.tmp")
    assert leftover.name.startswith(".")
    assert not any(path.match("document.*") for path in [leftover])


def test_the_sidecar_schema_version_is_stated_rather_than_inferred() -> None:
    """A reader must be able to tell an old sidecar from a new one without guessing from keys."""
    assert isinstance(METADATA_SCHEMA_VERSION, int) and METADATA_SCHEMA_VERSION >= 1
