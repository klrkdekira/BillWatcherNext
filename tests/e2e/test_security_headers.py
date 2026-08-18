"""The Content-Security-Policy is a property of the application, and it is asserted (HANDOFF 17).

It used to be set only by the reverse proxy, so a development server or any other deployment sent
no policy at all and nothing noticed. These tests are what makes the policy "tested" rather than
"configured somewhere".
"""

import hashlib
import re
from pathlib import Path

import pytest

from billwatcher.web.security_headers import CONTENT_SECURITY_POLICY, SECURITY_HEADERS
from billwatcher.web.templating import PACKAGE_DIR
from tests.e2e.test_web import client

VENDOR = PACKAGE_DIR / "static" / "vendor"


def directives(policy: str) -> dict[str, set[str]]:
    parsed = {}
    for directive in policy.split(";"):
        name, *values = directive.split()
        parsed[name] = set(values)
    return parsed


@pytest.mark.parametrize("path", ["/", "/bills", "/status", "/changes", "/about"])
def test_every_page_carries_the_policy(path: str) -> None:
    response = client().get(path)
    assert response.status_code == 200
    for header, value in SECURITY_HEADERS.items():
        assert response.headers[header] == value


def test_the_policy_grants_unsafe_eval_and_nothing_else_loose() -> None:
    """`unsafe-eval` is the one concession ADR-012 records. Nothing else may creep in beside it."""
    policy = directives(client().get("/").headers["content-security-policy"])
    assert policy["script-src"] == {"'self'", "'unsafe-eval'"}
    # An injected <script> tag or inline handler is still refused.
    assert "'unsafe-inline'" not in policy["script-src"]
    assert "'unsafe-inline'" not in policy["style-src"]
    # No third-party origin may supply anything, and the page may not be framed.
    assert policy["default-src"] == {"'self'"}
    assert policy["frame-ancestors"] == {"'none'"}
    assert policy["object-src"] == {"'none'"}
    assert policy["form-action"] == {"'self'"}
    assert policy["base-uri"] == {"'self'"}
    # `data:` is allowed for images only, and no host wildcard appears anywhere.
    assert policy["img-src"] == {"'self'", "data:"}
    assert "*" not in CONTENT_SECURITY_POLICY
    assert "http:" not in CONTENT_SECURITY_POLICY


def test_no_page_loads_a_third_party_asset() -> None:
    """`default-src 'self'` is only a guarantee if nothing on the page needs more than that.

    Links out to Parliament are the point of the site and are allowed; what may not appear is an
    asset — a script, stylesheet, image, or font — from anywhere but this origin.
    """
    page = client()
    for path in ("/", "/bills", "/status", "/ask"):
        body = page.get(path).text
        assets = re.findall(r'(?:<script[^>]*src|<link[^>]*href|<img[^>]*src)="([^"]+)"', body)
        assert assets, f"{path} referenced no assets at all; the check would pass vacuously"
        for url in assets:
            origin = url.split("//", 1)[-1].split("/", 1)[0] if "//" in url else ""
            assert origin in {"", "testserver"}, f"{path} loads {url} from a third party"


def test_the_vendored_bundle_matches_its_recorded_digest() -> None:
    """A vendored script is only trustworthy while it is the file that was reviewed."""
    readme = (VENDOR / "README.md").read_text()
    recorded = dict(re.findall(r"`(datastar-[\d.]+\.js)`.*?`([0-9a-f]{64})`", readme))
    assert recorded, "the vendor README records no digest"
    for name, digest in recorded.items():
        path = VENDOR / name
        assert path.exists(), f"{name} is recorded but not committed"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    # And nothing else is being served out of the vendor directory unrecorded.
    committed = {path.name for path in VENDOR.iterdir() if path.suffix == ".js"}
    assert committed == set(recorded)


def test_nothing_in_the_repository_sets_a_second_policy() -> None:
    """Two policies are intersected by the browser, so a stale copy breaks the site silently.

    TLS is terminated outside this repository (ADR-015), so no proxy config lives here to drift.
    """
    for name in ("Caddyfile", "nginx.conf", "default.conf"):
        assert not Path(name).exists(), f"{name} would be a second source of these headers"
    compose = Path("compose.yaml").read_text()
    assert "Content-Security-Policy" not in compose
    assert "Strict-Transport-Security" not in compose


def test_hsts_is_off_by_default_and_can_be_turned_on() -> None:
    """A year-long promise made before HTTPS works takes the domain down (HANDOFF 17)."""
    from billwatcher.config import Settings
    from billwatcher.web.security_headers import strict_transport_security

    assert Settings().hsts_max_age_seconds == 0
    assert "strict-transport-security" not in {key.lower() for key in client().get("/").headers}

    enabled = client(hsts_max_age_seconds=31_536_000)
    assert enabled.get("/").headers["strict-transport-security"] == (
        "max-age=31536000; includeSubDomains"
    )
    # `preload` is never emitted: it is a decision with a slow exit.
    assert "preload" not in strict_transport_security(31_536_000)
