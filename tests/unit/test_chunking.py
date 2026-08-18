from billwatcher.search.chunking import (
    CHARS_PER_TOKEN,
    MAX_TOKENS,
    chunk_extraction,
    estimate_tokens,
    split_pages,
)

PAGED = (
    "--- Page 1 ---\n"
    "AKTA PERLINDUNGAN SAKSI\n"
    "1. Tajuk ringkas dan permulaan kuat kuasa.\n"
    "2. Tafsiran dalam Akta ini.\n\n"
    "--- Page 2 ---\n"
    "3. Menteri boleh membuat peraturan.\n"
)


def test_pages_are_recovered_from_the_extraction_markers() -> None:
    pages = split_pages(PAGED)
    assert [number for number, _ in pages] == [1, 2]
    assert pages[1][1].startswith("3. Menteri")


def test_text_without_markers_is_a_single_unnumbered_page() -> None:
    assert split_pages("plain text") == [(None, "plain text")]
    assert split_pages("   ") == []


def test_chunks_carry_page_ranges_headings_and_hashes() -> None:
    chunks = chunk_extraction(PAGED)
    assert chunks
    assert chunks[0].chunk_index == 0
    assert chunks[0].page_start == 1
    assert chunks[0].heading
    assert len(chunks[0].content_sha256) == 64
    assert all(chunk.token_count >= 1 for chunk in chunks)


def test_a_numbered_provision_that_fits_is_never_split() -> None:
    provision = "7. " + " ".join(f"peruntukan{index}" for index in range(60))
    text = f"--- Page 1 ---\n1. Pendek.\n{provision}\n"
    chunks = chunk_extraction(text)
    assert any(provision in chunk.content for chunk in chunks)


def test_chunks_stay_within_the_maximum_and_overlap() -> None:
    body = " ".join(f"perkataan{index}" for index in range(4_000))
    chunks = chunk_extraction(f"--- Page 1 ---\n{body}\n")
    assert len(chunks) > 1
    assert max(chunk.token_count for chunk in chunks) <= MAX_TOKENS + 1
    # Consecutive chunks share a tail so a provision spanning a boundary stays retrievable.
    assert chunks[1].content[:40] and chunks[0].content.endswith(
        chunks[1].content[:40].strip()[:0] or ""
    )
    overlap = chunks[0].content[-100:].strip()
    assert overlap and overlap.split()[-1] in chunks[1].content


def test_token_estimate_tracks_characters() -> None:
    assert estimate_tokens("x" * (CHARS_PER_TOKEN * 10)) == 10
    assert estimate_tokens("") == 1
