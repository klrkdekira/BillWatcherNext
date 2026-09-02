"""The second reading and the comparison over it (ADR-035 decisions 5 and 6)."""

from pathlib import Path

import pytest

from billwatcher.markdown.crosscheck import (
    MIN_AGREEMENT,
    agreement,
    cross_reference,
    import_crosscheck,
    import_crosscheck_tree,
)
from billwatcher.markdown.imports import MarkdownImportError, Producer, import_markdown
from billwatcher.store import FileStore
from tests.support.pdfs import sample_bill

FIRST = "1. Tajuk ringkas dan permulaan kuat kuasa.\n\nAkta ini bolehlah dinamakan Akta Contoh.\n"


def seed(store: FileStore, *, slug: str = "dr-15-2026", key: str = "doc-abc123") -> dict:
    keys = {"bill_slug": slug, "doc_key": key, "version": 1}
    store.save_bill(slug, {"identifier": {"slug": slug}})
    store.save_document(
        **keys, content=sample_bill(), metadata={"source_url": f"https://example/{key}.pdf"}
    )
    return keys


def read_first(store: FileStore, keys: dict, text: str = FIRST) -> None:
    import_markdown(
        store, **keys, markdown_text=text, language="ms", producer=Producer(tool="pdfminer-layout")
    )


def test_two_readings_of_one_document_are_measured_symmetrically() -> None:
    """Neither reading is the reference, so the measure must not favour a direction.

    A one-sided measure hides the direction it does not look in — and that direction is where a
    reading which *invents* text shows up.
    """
    short = "Akta ini bolehlah dinamakan Akta Contoh."
    padded = short + " Dan satu ayat tambahan yang direka sepenuhnya oleh pembaca kedua."

    assert agreement(short, padded) == agreement(padded, short)
    assert agreement(short, short) == 1.0
    # The invention costs agreement even though the second reading contains all of the first.
    assert agreement(short, padded) < 1.0


def test_furniture_and_ordering_are_not_treated_as_disagreement() -> None:
    """Two readers render page markers, notes and table cells differently without disagreeing."""
    with_furniture = "<!-- page 1 -->\n\n<!-- marginal: Tajuk ringkas -->\n\nAkta ini bolehlah."
    without = "Bolehlah ini Akta."

    assert agreement(with_furniture, without) == 1.0


def test_a_cross_check_reading_lands_beside_the_first_and_never_over_it(tmp_path) -> None:
    """The whole value of a second reading is the divergence; overwriting the first destroys it."""
    store = FileStore(tmp_path / "store")
    keys = seed(store)
    read_first(store, keys)

    import_crosscheck(
        store, **keys, markdown_text="Satu bacaan kedua.", producer=Producer(tool="mineru")
    )

    assert store.load_markdown(**keys) == FIRST
    assert store.load_crosscheck(**keys) == "Satu bacaan kedua."
    record = store.load_provenance(**keys, artifact="crosscheck")
    assert record is not None
    assert record["inputs"]["producer"] == "mineru"
    # The link back to the bytes both readings claim to read, exactly as the markdown record has it.
    markdown_record = store.load_provenance(**keys, artifact="markdown")
    assert markdown_record is not None
    assert record["inputs"]["source_files"] == markdown_record["inputs"]["source_files"]


def test_a_cross_check_does_not_get_to_declare_the_documents_language(tmp_path) -> None:
    """The language is a permanent component of the Expression IRI, and has exactly one answer."""
    store = FileStore(tmp_path / "store")
    keys = seed(store)
    read_first(store, keys)
    import_crosscheck(
        store, **keys, markdown_text="Satu bacaan kedua.", producer=Producer(tool="mineru")
    )

    record = store.load_provenance(**keys, artifact="crosscheck")
    assert record is not None
    assert "language" not in record["inputs"]


def test_readings_that_agree_are_counted_not_reported(tmp_path) -> None:
    store = FileStore(tmp_path / "store")
    keys = seed(store)
    read_first(store, keys)
    import_crosscheck(store, **keys, markdown_text=FIRST, producer=Producer(tool="mineru"))

    result = cross_reference(store)

    assert result.counts["compared"] == 1
    assert result.counts["agreed"] == 1
    assert result.counts["diverged"] == 0
    assert result.failures == ()


def test_a_divergence_names_the_document_the_score_and_who_disagreed(tmp_path) -> None:
    store = FileStore(tmp_path / "store")
    keys = seed(store)
    read_first(store, keys)
    import_crosscheck(
        store,
        **keys,
        markdown_text="Peruntukan yang berbeza sepenuhnya tentang perkara lain sama sekali.",
        producer=Producer(tool="mineru"),
    )

    result = cross_reference(store)

    assert result.counts["diverged"] == 1
    (failure,) = result.failures
    assert failure.label == "dr-15-2026/doc-abc123/v001"
    assert "readings disagree" in failure.reason
    assert "mineru" in failure.reason


def test_a_document_with_one_reading_is_unchecked_not_failed(tmp_path) -> None:
    """On a corpus cross-checked incrementally this is the ordinary state of most documents."""
    store = FileStore(tmp_path / "store")
    keys = seed(store)
    read_first(store, keys)

    result = cross_reference(store)

    assert result.counts["unchecked"] == 1
    assert result.counts["compared"] == 0
    assert result.failures == ()


def test_divergences_are_reported_worst_first(tmp_path) -> None:
    """This list is worked through by a person, so the most damaged document comes first."""
    store = FileStore(tmp_path / "store")
    near = seed(store, slug="dr-1-2026", key="doc-near01")
    far = seed(store, slug="dr-2-2026", key="doc-far002")
    for keys in (near, far):
        read_first(store, keys)
    import_crosscheck(
        store,
        **near,
        markdown_text=FIRST + "\n\nSatu ayat tambahan yang panjang dan berbeza sama sekali.",
        producer=Producer(tool="mineru"),
    )
    import_crosscheck(
        store, **far, markdown_text="Tiada kaitan langsung.", producer=Producer(tool="mineru")
    )

    result = cross_reference(store, min_agreement=1.0)

    assert [failure.label for failure in result.failures] == [
        "dr-2-2026/doc-far002/v001",
        "dr-1-2026/doc-near01/v001",
    ]


def test_a_mirrored_tree_imports_every_second_reading_and_settles(tmp_path) -> None:
    store = FileStore(tmp_path / "store")
    keys = seed(store)
    read_first(store, keys)
    packet = tmp_path / "second" / "dr-15-2026" / "doc-abc123" / "v001"
    packet.mkdir(parents=True)
    packet.joinpath("document.crosscheck.md").write_text("Satu bacaan kedua.", encoding="utf-8")
    (tmp_path / "second" / "not-a-document.md").write_text("x", encoding="utf-8")

    first = import_crosscheck_tree(
        store, source_root=tmp_path / "second", producer=Producer(tool="mineru")
    )
    again = import_crosscheck_tree(
        store, source_root=tmp_path / "second", producer=Producer(tool="mineru")
    )

    assert first.counts["imported"] == 1
    assert again.counts["imported"] == 0
    assert again.counts["unchanged"] == 1, "a repeat import must touch nothing"
    assert store.load_crosscheck(**keys) == "Satu bacaan kedua."


def test_a_second_reading_of_a_document_nobody_fetched_is_refused(tmp_path) -> None:
    store = FileStore(tmp_path / "store")

    with pytest.raises(MarkdownImportError) as error:
        import_crosscheck(
            store,
            bill_slug="dr-15-2026",
            doc_key="doc-abc123",
            version=1,
            markdown_text="Satu bacaan.",
            producer=Producer(tool="mineru"),
        )

    assert "fetch the PDF before importing a reading of it" in str(error.value)


def test_a_blank_second_reading_is_refused_like_any_other(tmp_path) -> None:
    """The shared refusals are shared, not reimplemented."""
    store = FileStore(tmp_path / "store")
    keys = seed(store)

    with pytest.raises(MarkdownImportError):
        import_crosscheck(store, **keys, markdown_text="   \n", producer=Producer(tool="mineru"))


def test_the_threshold_is_the_one_the_adr_set() -> None:
    """Deliberately far below Gate P1's 0.95: this is a substance line, not a fidelity score."""
    assert MIN_AGREEMENT == 0.75


def test_a_file_the_second_reader_named_its_own_way_still_imports(tmp_path) -> None:
    store = FileStore(tmp_path / "store")
    keys = seed(store)
    packet = tmp_path / "second" / "dr-15-2026" / "doc-abc123" / "v001"
    packet.mkdir(parents=True)
    packet.joinpath("mineru.md").write_text("Satu bacaan kedua.", encoding="utf-8")

    result = import_crosscheck_tree(
        store,
        source_root=Path(tmp_path / "second"),
        producer=Producer(tool="mineru"),
        filename="mineru.md",
    )

    assert result.counts["imported"] == 1
    assert store.load_crosscheck(**keys) == "Satu bacaan kedua."
