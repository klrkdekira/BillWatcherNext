"""The frontend must work with JavaScript disabled (HANDOFF 1 principle 5, HANDOFF 14).

Datastar is enhancement only. These tests assert the baseline is complete on its own and that
the enhanced paths render the same partials, so the two cannot drift.
"""

import re
from pathlib import Path

from tests.e2e.test_web import client

STATIC = Path("src/billwatcher/web/static")


def test_every_page_is_complete_without_running_any_script() -> None:
    with client() as browser:
        for path in ("/", "/bills", "/search?q=Perlindungan", "/bills/dr-15-2026", "/status"):
            page = browser.get(path)
            assert page.status_code == 200, path
            # The only script on the page is the vendored module; nothing is inline.
            assert "<script>" not in page.text, path
            body = page.text.split("</head>", 1)[-1]
            assert "<script" not in body, f"{path} has a script outside head"

        # The content itself is server-rendered, not fetched.
        assert "D.R.15/2026" in browser.get("/bills").text
        assert "1 result" in browser.get("/search", params={"q": "Perlindungan"}).text
        assert "Coverage targets" in browser.get("/status").text


def test_the_filter_form_is_a_plain_get_that_needs_no_script() -> None:
    with client() as browser:
        page = browser.get("/bills").text
        form = re.search(r"<form class=\"filters\"[^>]*>", page)
        assert form is not None
        assert 'method="get"' in form.group(0)
        assert 'action="/bills"' in form.group(0)
        # Submitting it normally works.
        filtered = browser.get("/bills", params={"chamber": "dewan_rakyat"})
        assert filtered.status_code == 200
        assert "D.R.15/2026" in filtered.text


def test_datastar_is_vendored_and_never_fetched_from_a_third_party() -> None:
    with client() as browser:
        page = browser.get("/").text
        assert "/static/vendor/datastar-1.0.2.js" in page
        # No third-party origin appears anywhere in the markup.
        for host in ("cdn.jsdelivr.net", "unpkg.com", "cdnjs", "googleapis", "//data-star.dev"):
            assert host not in page, host
        assert browser.get("/static/vendor/datastar-1.0.2.js").status_code == 200


def test_the_vendored_bundle_matches_its_recorded_digest() -> None:
    import hashlib

    bundle = STATIC / "vendor" / "datastar-1.0.2.js"
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    recorded = (STATIC / "vendor" / "README.md").read_text()
    assert digest in recorded, "vendored bundle changed without updating its recorded digest"


def test_the_search_fragment_returns_a_datastar_element_patch() -> None:
    with client() as browser:
        response = browser.get("/fragments/search", params={"q": "Perlindungan"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.text.startswith("event: datastar-patch-elements\n")
        assert "data: elements " in response.text
        assert response.text.endswith("\n\n")
        # It patches the region the page already rendered, by id.
        assert 'id="search-results"' in response.text
        assert "D.R.15/2026" in response.text


def test_the_fragment_and_the_page_render_the_same_results() -> None:
    with client() as browser:
        page = browser.get("/search", params={"q": "Perlindungan"}).text
        fragment = browser.get("/fragments/search", params={"q": "Perlindungan"}).text
        for marker in ("D.R.15/2026", "<mark>Perlindungan</mark>", "1 result"):
            assert marker in page, marker
            assert marker in fragment, marker


def test_an_invalid_filter_patches_an_error_instead_of_breaking_the_page() -> None:
    with client() as browser:
        response = browser.get("/fragments/search", params={"chamber": "senate"})
        assert response.status_code == 200
        assert 'id="search-results"' in response.text
        assert "Unknown chamber filter" in response.text
        # The no-JavaScript path still returns a real 400.
        assert browser.get("/bills", params={"chamber": "senate"}).status_code == 400


def test_the_status_stream_emits_patches_and_then_closes() -> None:
    from billwatcher.web import routes

    original = routes.STATUS_STREAM_TICKS
    routes.STATUS_STREAM_TICKS = 2
    try:
        with client() as browser, browser.stream("GET", "/fragments/status") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["cache-control"] == "no-store"
            body = "".join(response.iter_text())
    finally:
        routes.STATUS_STREAM_TICKS = original

    assert body.count("event: datastar-patch-elements") == 2
    assert 'id="status-panel"' in body
    assert "Coverage targets" in body
    # The stream is bounded rather than endless.
    assert body.rstrip().endswith("stream complete; reconnect for more")


def test_the_status_page_and_its_stream_render_the_same_panel() -> None:
    from billwatcher.web import routes

    original = routes.STATUS_STREAM_TICKS
    routes.STATUS_STREAM_TICKS = 1
    try:
        with client() as browser:
            page = browser.get("/status").text
            with browser.stream("GET", "/fragments/status") as response:
                stream = "".join(response.iter_text())
    finally:
        routes.STATUS_STREAM_TICKS = original

    for marker in ("Coverage targets", "Queue depth", "Pipeline versions", "Recent runs"):
        assert marker in page, marker
        assert marker in stream, marker


def test_status_never_leaks_internals_through_the_stream() -> None:
    from billwatcher.web import routes

    original = routes.STATUS_STREAM_TICKS
    routes.STATUS_STREAM_TICKS = 1
    try:
        with client() as browser, browser.stream("GET", "/fragments/status") as response:
            stream = "".join(response.iter_text()).casefold()
    finally:
        routes.STATUS_STREAM_TICKS = original

    for secret in ("postgresql", "password", "traceback", "sqlite", "/home/"):
        assert secret not in stream, secret


def test_filter_values_reach_the_signals_attribute_safely() -> None:
    """A quote or angle bracket in a filter must not break out of the attribute."""
    with client() as browser:
        page = browser.get(
            "/bills", params={"q": 'O\'Brien "quoted" <script>alert(1)</script>'}
        ).text
        attribute = re.search(r"data-signals='([^']*)'", page)
        assert attribute is not None
        payload = attribute.group(1)
        # JSON-encoded and HTML-safe: no raw quote, apostrophe, or bracket survives.
        assert "'" not in payload
        assert "<" not in payload and ">" not in payload
        assert "\\u0027" in payload and "\\u003c" in payload
        assert "<script>alert(1)" not in page


def test_the_status_page_declares_its_stream_with_data_init() -> None:
    """A div never fires a load event, so the subscription must use data-init."""
    with client() as browser:
        page = browser.get("/status").text
        assert "data-init=\"@get('/fragments/status')\"" in page
        assert "data-on:load" not in page
