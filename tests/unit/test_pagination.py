import pytest

from billwatcher.scraper.pagination import PaginationGuard, PaginationLoop


def test_distinct_pages_advance_and_report_their_hash() -> None:
    guard = PaginationGuard(max_pages=5)
    first = guard.observe(b"<table>page one</table>")
    second = guard.observe(b"<table>page two</table>")
    assert first != second
    assert len(first) == 64
    assert guard.pages_seen == 2


def test_a_repeated_body_stops_the_crawl_instead_of_looping() -> None:
    guard = PaginationGuard()
    body = b"<table>same every time</table>"
    guard.observe(body)
    guard.observe(b"<table>something else</table>")
    with pytest.raises(PaginationLoop) as caught:
        guard.observe(body)
    assert caught.value.page == 3
    assert "first seen on page 1" in str(caught.value)
    assert caught.value.content_sha256


def test_the_page_budget_is_bounded() -> None:
    guard = PaginationGuard(max_pages=3)
    for index in range(3):
        guard.observe(f"page {index}".encode())
    with pytest.raises(PaginationLoop, match="exceeded 3 pages"):
        guard.observe(b"page 4")
