"""The cheap local markdown reading, and the quality signals that decide what to cross-check."""

from billwatcher.graph.fidelity import tokens_for_comparison
from billwatcher.markdown.layout import Line
from billwatcher.markdown.reading import (
    SUSPECT_HEADING_RATIO,
    extract_markdown,
    lines_to_markdown,
    measure,
    read_document_markdown,
)
from billwatcher.store import FileStore
from tests.support.pdfs import sample_bill


def line(text: str, role: str, *, page: int = 1, y: float = 700.0, x0: float = 72.0) -> Line:
    return Line(page=page, x0=x0, y=y, size=10.0, font="Times", text=text, role=role)


def test_a_marginal_note_is_never_spliced_into_the_provision_it_annotates() -> None:
    """The case ADR-016 exists for. A marginal note shares its baseline with the provision, so a
    reader that joins them puts an annotation inside the legal text and looks well-formed doing it.
    """
    markdown = lines_to_markdown(
        (
            line("5. Seksyen 5 Akta ibu dipinda—", "provision"),
            line("Pindaan seksyen 5", "marginal", x0=430.0),
            line("(a) dalam subseksyen (6),", "body"),
        )
    )

    assert "5. Seksyen 5 Akta ibu dipinda—" in markdown
    assert "<!-- marginal: Pindaan seksyen 5 -->" in markdown
    # The annotation is not inside the provision's own paragraph...
    assert "dipinda— Pindaan" not in markdown
    assert "Pindaan seksyen 5 (a) dalam" not in markdown
    # ...and it contributes no tokens to what a provision tree is judged against.
    assert "pindaan" not in tokens_for_comparison(markdown)


def test_a_marginal_note_cannot_break_out_of_its_own_comment() -> None:
    """`-->` inside a note would close the comment early and leave the rest as body text, which is
    how an annotation would get counted as enacted text after all."""
    markdown = lines_to_markdown((line("see --> clause 4 > 2", "marginal", x0=430.0),))

    # Two closers only: the page marker's own, and the one closing the marginal note. The `-->`
    # that was *inside* the note is gone, so the note cannot terminate itself early.
    assert markdown.count("-->") == 2
    assert markdown == "<!-- page 1 -->\n\n<!-- marginal: see -- clause 4 ) 2 -->"
    assert tokens_for_comparison(markdown) == []


def test_body_lines_join_into_one_paragraph_per_provision() -> None:
    markdown = lines_to_markdown(
        (
            line("## tidak", "heading"),
            line("1. Akta ini bolehlah", "provision"),
            line("dinamakan Akta Contoh 2026.", "body"),
            line("2. Akta ini mula berkuat kuasa.", "provision"),
        )
    )
    blocks = [b for b in markdown.split("\n\n") if not b.startswith("<!--")]
    assert blocks == [
        # `###`, not `##`: a heading that names no Part, Chapter or Schedule and is not set in
        # display capitals is one provision's own heading, which sits under them.
        "### ## tidak",
        "1. Akta ini bolehlah dinamakan Akta Contoh 2026.",
        "2. Akta ini mula berkuat kuasa.",
    ]


def test_a_document_division_outranks_one_provisions_heading() -> None:
    """Both are headings to the classifier; flattening them lost what a reader needs from them.

    `BAHAGIAN II` opens a Part that runs for pages. `Pindaan seksyen 5` labels the single
    provision beneath it. Emitting both as `##` said they were the same kind of thing.
    """
    markdown = lines_to_markdown(
        (
            line("SUSUNAN FASAL", "heading"),
            line("BAHAGIAN II", "heading"),
            line("JADUAL KETIGA", "heading"),
            line("Pindaan seksyen 5", "heading"),
        )
    )
    blocks = [b for b in markdown.split("\n\n") if not b.startswith("<!--")]
    assert blocks == [
        "## SUSUNAN FASAL",
        "## BAHAGIAN II",
        "## JADUAL KETIGA",
        "### Pindaan seksyen 5",
    ]


def test_every_heading_level_counts_towards_the_heading_ratio() -> None:
    """The measure looked for `## ` alone, so a document of section headings scored zero."""
    assert measure("\n\n".join(["### one", "### two", "### three", "body"]))["heading_ratio"] >= (
        SUSPECT_HEADING_RATIO
    )


def test_a_page_boundary_is_marked_the_way_the_other_reading_marks_it() -> None:
    """Both readings must cite pages identically or a divergence report compares formatting."""
    markdown = lines_to_markdown((line("first", "body", page=1), line("second", "body", page=2)))
    assert markdown.splitlines()[0] == "<!-- page 1 -->"
    assert "<!-- page 2 -->" in markdown


def test_a_reading_that_is_only_page_markers_is_empty_not_succeeded() -> None:
    """What a scan with no text layer produces. Calling it a success would hand the next step a
    document nobody has read, and Gate P1's `no_source_text` exists for exactly this."""
    from billwatcher.markdown.reading import _has_body

    assert _has_body("<!-- page 1 -->\n\n<!-- page 2 -->") is False
    assert _has_body("<!-- page 1 -->\n\ntext") is True


def test_non_pdf_bytes_fail_rather_than_read_as_empty() -> None:
    reading = read_document_markdown(b"<html>not a pdf</html>")
    assert reading.status == "failed"
    assert reading.error is not None
    assert reading.markdown == ""


def test_heading_inflation_marks_a_reading_suspect() -> None:
    """~1 in 6 documents in the real corpus come back mostly headings (worst measured: 90%). The
    reading is still written; it is the cross-check priority list that this feeds."""
    mostly_headings = "\n\n".join(["## one", "## two", "## three", "body text here"])
    quality = measure(mostly_headings)
    assert quality["heading_ratio"] >= SUSPECT_HEADING_RATIO

    ordinary = "\n\n".join(["## one", "body a", "body b", "body c"])
    assert measure(ordinary)["heading_ratio"] < SUSPECT_HEADING_RATIO


def test_the_cover_pages_display_typography_is_not_counted_as_damage() -> None:
    """A bill's cover prints "b e r n a m a" letter-spaced on purpose. Counting page one would
    flag every document in the corpus for something that is in the paper, not in the reading."""
    cover_only = "<!-- page 1 -->\n\nb e r n a m a\n\n<!-- page 2 -->\n\nordinary body text"
    assert measure(cover_only)["lone_letter_rate"] == 0.0

    damaged = "<!-- page 1 -->\n\ncover\n\n<!-- page 2 -->\n\nSuatu Akta u n t uk meminda"
    assert measure(damaged)["lone_letter_rate"] > 0.0


def test_a_document_with_no_text_layer_is_named_as_empty_not_counted_as_failed(tmp_path) -> None:
    """Twelve real documents in the corpus behave this way: no text layer means no content lines,
    so the reading is the empty string and `import_markdown` rightly refuses it. Counting that as
    both `empty` and `failed` double-reported one outcome, and named it with an import error that
    told an operator nothing about the document.
    """
    import io

    from pypdf import PdfWriter

    from billwatcher.download.documents import doc_key
    from billwatcher.markdown.reading import extract_markdown
    from billwatcher.store import FileStore

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)  # a page with no text on it at all
    buffer = io.BytesIO()
    writer.write(buffer)

    store = FileStore(tmp_path)
    url = "https://www.parlimen.gov.my/scan.pdf"
    key = doc_key(url)
    store.save_bill("dr-15-2026", {"identifier": {"slug": "dr-15-2026"}})
    store.save_document(
        bill_slug="dr-15-2026",
        doc_key=key,
        version=1,
        content=buffer.getvalue(),
        metadata={"source_url": url},
    )

    result = extract_markdown(store, language="ms")

    assert result.counts["empty"] == 1
    assert result.counts["failed"] == 0
    assert result.counts["written"] == 0
    (failure,) = result.failures
    assert "no text layer" in failure.reason
    assert "cross-check tier" in failure.reason
    assert store.has_markdown(bill_slug="dr-15-2026", doc_key=key, version=1) is False


def _seed_document(store, *, slug: str, key: str) -> dict:
    """One stored bill and one stored PDF that actually has a text layer to read."""
    keys = {"bill_slug": slug, "doc_key": key, "version": 1}
    store.save_bill(slug, {"identifier": {"slug": slug}})
    store.save_document(
        **keys, content=sample_bill(), metadata={"source_url": f"https://example/{key}.pdf"}
    )
    return keys


def test_a_reading_that_is_already_current_is_not_read_again(tmp_path, monkeypatch) -> None:
    """A repeat run must not pay for the PDF read it is going to discard.

    `import_markdown` already made a repeat run *write* nothing, but only after re-reading every
    document — about a second each, so twenty minutes of work for zero output over this corpus, on
    every `make build`. The provenance record answers the question up front, so the second run does
    not open the PDF at all.
    """
    from billwatcher.markdown import reading as reading_module

    store = FileStore(tmp_path / "store")
    keys = _seed_document(store, slug="dr-1-2026", key="doc-abc123")

    first = extract_markdown(store, language="ms")
    assert first.counts["read"] == 1
    assert first.counts["skipped_current"] == 0
    assert store.has_markdown(**keys)

    reads = 0
    original = reading_module.read_document_markdown

    def counting(content: bytes):  # type: ignore[no-untyped-def]
        nonlocal reads
        reads += 1
        return original(content)

    monkeypatch.setattr(reading_module, "read_document_markdown", counting)
    second = extract_markdown(store, language="ms")

    assert reads == 0, "the PDF was read again even though its reading was already current"
    assert second.counts["skipped_current"] == 1
    assert second.counts["read"] == 0
    assert second.counts["written"] == 0


def test_a_new_producer_version_re_reads_the_document(tmp_path, monkeypatch) -> None:
    """The skip must not outlive the reason for it: a code bump has to re-derive the corpus once."""
    from billwatcher.markdown import reading as reading_module

    store = FileStore(tmp_path / "store")
    _seed_document(store, slug="dr-2-2026", key="doc-def456")
    extract_markdown(store, language="ms")

    monkeypatch.setattr(reading_module, "LOCAL_READING_VERSION", "2.0.0")
    again = extract_markdown(store, language="ms")

    assert again.counts["skipped_current"] == 0
    assert again.counts["read"] == 1


def test_each_document_is_read_in_the_language_of_the_listing_that_named_it(tmp_path) -> None:
    """One `--language` for the whole run would stamp the English half of the corpus as Malay, and
    the language is a permanent component of the Expression IRI (ADR-024, ADR-040). The bill record
    already knows which listing language named each file, so that is what the reading records.
    """
    from billwatcher.download.documents import doc_key

    store = FileStore(tmp_path)
    malay_url = "https://example.org/DR 17 BM.pdf"
    english_url = "https://example.org/DR 17 BI.pdf"
    both_url = "https://example.org/DR012011.pdf"
    store.save_bill(
        "dr-17-2024",
        {
            "identifier": {"slug": "dr-17-2024"},
            "documents": [
                {"url": malay_url, "languages": ["ms"]},
                {"url": english_url, "languages": ["en"]},
                {"url": both_url, "languages": ["en", "ms"]},
            ],
        },
    )
    for url in (malay_url, english_url, both_url):
        store.save_document(
            bill_slug="dr-17-2024",
            doc_key=doc_key(url),
            version=1,
            content=sample_bill(),
            metadata={"source_url": url},
        )

    result = extract_markdown(store, language="ms")

    assert result.counts["written"] == 3
    assert result.counts["language_from_listing"] == 2
    # The file both languages link is what `--language` is still there for.
    assert result.counts["language_fallback"] == 1
    recorded = {
        url: (
            store.load_provenance(
                bill_slug="dr-17-2024", doc_key=doc_key(url), version=1, artifact="markdown"
            )
            or {}
        )["inputs"]["language"]
        for url in (malay_url, english_url, both_url)
    }
    assert recorded == {malay_url: "ms", english_url: "en", both_url: "ms"}


def test_a_paragraph_break_marked_by_space_alone_separates_two_blocks() -> None:
    """Malaysian bills separate the long title, the empty citation bracket and the enacting
    formula with vertical space and nothing else — no number, no heading, no note.

    Before the reader carried `opens_block`, the only things that ended a paragraph were a role
    change and a page boundary, so all three ran together into one block. A marginal note used to
    hide this by accident: it forced a flush between them, and no longer does now that half a
    bracket pair is not read as a note.
    """
    markdown = lines_to_markdown(
        (
            line("Suatu Akta untuk meminda Akta Contoh 2001.", "body"),
            # No `opens_block`: `_classify` withholds it from a line of pure punctuation, which
            # is what keeps the bracket with the title rather than alone in a block of its own.
            line("[", "body"),
            _spaced("DIPERBUAT oleh Parlimen Malaysia seperti yang berikut:", "body"),
        )
    )

    blocks = [b for b in markdown.split("\n\n") if not b.startswith("<!--")]
    assert blocks == [
        "Suatu Akta untuk meminda Akta Contoh 2001. [",
        "DIPERBUAT oleh Parlimen Malaysia seperti yang berikut:",
    ], "the bracket belongs to the title it is printed against; the formula is its own block"


def _spaced(text: str, role: str) -> Line:
    """A line the reader measured a block of space above."""
    return Line(
        page=1,
        x0=72.0,
        y=700.0,
        size=10.0,
        font="Times",
        text=text,
        role=role,
        opens_block=True,
    )


def test_a_reading_another_tool_produced_survives_the_local_step(tmp_path) -> None:
    """The work `import-markdown` exists to accept must not be destroyed by the next `make build`.

    An imported reading records the operator's own producer, which never matches this step's, so
    `needs_rebuild` reported it stale on every run and the PDF was re-read over it — silently, and
    as a stage of `make build`, so the better reading was lost without anybody running the step
    that lost it.
    """
    from billwatcher.markdown.imports import Producer, import_markdown

    store = FileStore(tmp_path / "store")
    keys = _seed_document(store, slug="dr-3-2026", key="doc-ghi789")
    corrected = "# Rang Undang-Undang\n\nSatu bacaan yang diperbaiki dengan tangan.\n"
    import_markdown(
        store,
        **keys,
        markdown_text=corrected,
        language="ms",
        producer=Producer(tool="claude-opus-5", model_id="claude-opus-5"),
    )

    result = extract_markdown(store, language="ms")

    assert result.counts["kept_foreign"] == 1
    assert result.counts["read"] == 0
    assert result.counts["written"] == 0
    assert store.load_markdown(**keys) == corrected


def test_the_local_reading_can_be_asked_for_back(tmp_path) -> None:
    """`--replace-foreign` is the deliberate override, and it has to actually override."""
    from billwatcher.markdown.imports import Producer, import_markdown

    store = FileStore(tmp_path / "store")
    keys = _seed_document(store, slug="dr-4-2026", key="doc-jkl012")
    import_markdown(
        store,
        **keys,
        markdown_text="Satu bacaan yang diperbaiki dengan tangan.\n",
        language="ms",
        producer=Producer(tool="claude-opus-5"),
    )

    result = extract_markdown(store, language="ms", replace_foreign=True)

    assert result.counts["kept_foreign"] == 0
    assert result.counts["read"] == 1
    assert "Tajuk ringkas" in (store.load_markdown(**keys) or "")


def test_the_local_step_still_re_reads_its_own_stale_readings(tmp_path, monkeypatch) -> None:
    """Protecting another tool's reading must not protect this step's from its own version bump."""
    from billwatcher.markdown import reading as reading_module

    store = FileStore(tmp_path / "store")
    _seed_document(store, slug="dr-5-2026", key="doc-mno345")
    extract_markdown(store, language="ms")

    monkeypatch.setattr(reading_module, "LOCAL_READING_VERSION", "9.9.9")
    again = extract_markdown(store, language="ms")

    assert again.counts["kept_foreign"] == 0
    assert again.counts["read"] == 1


def test_the_lone_letter_measure_does_not_count_the_languages_real_one_letter_words() -> None:
    """An English bill's articles alone put it near the threshold; "a", "A" and "I" are words."""
    page = "<!-- page 1 -->\n\ncover\n\n<!-- page 2 -->\n\n"
    english = page + "Where a person makes a claim, a court may on a day it appoints hear it. " * 20
    assert measure(english)["lone_letter_rate"] == 0.0
    damaged = page + "t h e c o u r t m a y o n t h a t d a y " * 20
    assert measure(damaged)["lone_letter_rate"] > 6.0


def test_a_ratio_over_almost_nothing_cannot_flag_a_reading() -> None:
    """Two stray letters in a one-page body read as a rate of twelve; that is noise, not damage."""
    from billwatcher.markdown.reading import LocalReading

    def reading(quality: dict[str, float]) -> LocalReading:
        return LocalReading(
            extractor_name="pdfminer-layout",
            extractor_version="0",
            mode="geometry",
            status="succeeded",
            markdown="",
            markdown_sha256="",
            page_count=2,
            char_count=0,
            duration_ms=0,
            quality=quality,
        )

    tiny = reading(
        {"lone_letter_rate": 12.0, "lone_letters": 2.0, "heading_ratio": 0.67, "blocks": 6.0}
    )
    assert tiny.suspect is False
    damaged = reading({"lone_letter_rate": 12.0, "lone_letters": 300.0})
    assert damaged.suspect is True


def test_a_supply_bills_vote_codes_are_labels_not_damage() -> None:
    """A Supply Bill's schedule stamps "B 4", "B 10" beside every amount; a letter labelling a
    figure is the paper's own notation, while damage is always followed by more letters."""
    page = "<!-- page 1 -->\n\ncover\n\n<!-- page 2 -->\n\n"
    schedule = (
        page
        + "B 4 Suruhanjaya Pilihan Raya 31,571,643\n\nB 6 Jabatan Perdana Menteri 104,067,500\n\n"
        * 30
    )
    assert measure(schedule)["lone_letter_rate"] == 0.0


def test_the_assembly_writes_one_geometry_record_per_markdown_block() -> None:
    """The sidecar lines up with `markdown.split("\\n\\n")` index for index (ADR-042): page markers
    and marginal comments are blocks too, and a paragraph's record is its first line's."""
    from billwatcher.markdown.reading import assemble_markdown

    lines = (
        Line(
            page=1,
            x0=85.0,
            y=700.0,
            size=10.0,
            font="Times",
            text="1. Tajuk",
            role="provision",
            indent=0.0,
            lead_font="Times-Bold",
        ),
        Line(
            page=1,
            x0=85.0,
            y=688.0,
            size=10.0,
            font="Times",
            text="lanjutan baris",
            role="body",
            indent=0.0,
        ),
        Line(
            page=1,
            x0=430.0,
            y=688.0,
            size=8.0,
            font="Times",
            text="Tajuk ringkas",
            role="marginal",
            indent=345.0,
        ),
        Line(
            page=1,
            x0=133.0,
            y=670.0,
            size=10.0,
            font="Times",
            text="(a) perenggan",
            role="provision",
            indent=48.0,
        ),
        Line(
            page=2,
            x0=85.0,
            y=700.0,
            size=10.0,
            font="Times",
            text="2. Tafsiran",
            role="provision",
            indent=0.0,
        ),
    )
    markdown, blocks = assemble_markdown(lines)
    parts = markdown.split("\n\n")
    assert len(parts) == len(blocks)
    assert parts[0] == "<!-- page 1 -->" and blocks[0]["role"] == "page"
    assert parts[1] == "1. Tajuk lanjutan baris"
    assert blocks[1] == {"page": 1, "indent": 0.0, "role": "provision", "lead": "bold"}
    assert parts[2].startswith("<!-- marginal:") and blocks[2]["role"] == "marginal"
    assert blocks[3]["indent"] == 48.0
    assert parts[4] == "<!-- page 2 -->"
