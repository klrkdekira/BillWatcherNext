from mineru_vl_utils.structs import ContentBlock

from billwatcher.mineru.markdown import block_to_markdown, page_to_markdown, pages_to_markdown


def block(type: str, content: str | None = None, *, merge_prev: bool = False) -> ContentBlock:
    return ContentBlock(
        type=type, bbox=[0.1, 0.1, 0.9, 0.2], content=content, merge_prev=merge_prev
    )


def test_text_block_becomes_a_paragraph() -> None:
    assert block_to_markdown(block("text", "Akta ini bolehlah dinamakan Akta Contoh 2026.")) == (
        "Akta ini bolehlah dinamakan Akta Contoh 2026."
    )


def test_headings_get_their_level_from_block_type() -> None:
    assert block_to_markdown(block("doc_title", "Akta Contoh 2026")) == "# Akta Contoh 2026"
    assert block_to_markdown(block("title", "Bahagian I")) == "## Bahagian I"
    assert block_to_markdown(block("paragraph_title", "Tajuk ringkas")) == "### Tajuk ringkas"


def test_table_content_passes_through_as_html() -> None:
    html = "<table><tr><td>Seksyen</td><td>Tajuk</td></tr></table>"
    assert block_to_markdown(block("table", html)) == html


def test_equation_is_wrapped_in_display_math() -> None:
    assert block_to_markdown(block("equation", "x^2 + y^2 = z^2")) == "$$\nx^2 + y^2 = z^2\n$$"


def test_list_item_becomes_a_bullet() -> None:
    assert block_to_markdown(block("list_item", "melalui apa-apa cara yang ditetapkan")) == (
        "- melalui apa-apa cara yang ditetapkan"
    )


def test_furniture_types_contribute_nothing() -> None:
    for furniture_type in ("header", "footer", "page_number", "page_footnote"):
        assert block_to_markdown(block(furniture_type, "Akta Contoh 2026")) is None


def test_a_block_with_no_content_contributes_nothing() -> None:
    assert block_to_markdown(block("image")) is None
    assert block_to_markdown(block("text", "")) is None
    assert block_to_markdown(block("text", "   ")) is None


def test_page_assembly_drops_furniture_and_joins_in_order() -> None:
    blocks = [
        block("header", "Akta Contoh 2026"),
        block("doc_title", "Akta Contoh 2026"),
        block("text", "Perenggan pertama."),
        block("text", "Perenggan kedua."),
        block("page_number", "1"),
    ]
    assert page_to_markdown(blocks) == (
        "# Akta Contoh 2026\n\nPerenggan pertama.\n\nPerenggan kedua."
    )


def test_merge_prev_joins_a_text_block_onto_the_previous_paragraph() -> None:
    blocks = [
        block("text", "Seseorang yang melanggar seksyen 3"),
        block("text", "melakukan suatu kesalahan.", merge_prev=True),
    ]
    assert page_to_markdown(blocks) == (
        "Seseorang yang melanggar seksyen 3 melakukan suatu kesalahan."
    )


def test_merge_prev_with_nothing_before_it_is_not_dropped() -> None:
    blocks = [block("text", "carried over from a truncated previous page", merge_prev=True)]
    assert page_to_markdown(blocks) == "carried over from a truncated previous page"


def test_pages_to_markdown_marks_each_page_boundary() -> None:
    pages = [
        [block("text", "Page one content.")],
        [block("text", "Page two content.")],
    ]
    assert pages_to_markdown(pages) == (
        "<!-- page 1 -->\n\nPage one content.\n\n<!-- page 2 -->\n\nPage two content."
    )


def test_pages_to_markdown_keeps_the_marker_for_a_page_with_no_body_content() -> None:
    pages = [[block("header", "Akta Contoh 2026")]]
    assert pages_to_markdown(pages) == "<!-- page 1 -->"
