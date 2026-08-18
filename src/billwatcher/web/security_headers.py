"""The response security headers, owned by the application (HANDOFF 17).

These used to live only in a reverse-proxy config, which made the policy a property of one
deployment rather than of the site: `make serve` sent no policy at all, nothing tested it, and a
deployment behind a different proxy shipped without one. Since TLS is now terminated by a proxy
outside this repository (ADR-015), the application is the only place that can own them, and it does
— so the policy travels with the code and is asserted by the suite.

The reverse proxy should not set its own copies. A browser enforces the intersection of two
Content-Security-Policies, so a second, stale copy breaks the site rather than protecting it.

HSTS is the exception, and it is off by default. It is a promise about the *transport*, which this
process cannot verify from behind a proxy, and it is the one header that does real damage when it is
wrong: a year-long `max-age` on a domain whose certificate is not working yet takes the site down
for every browser that saw it. HANDOFF 17 says to add it "only after HTTPS/domain correctness is
established", so it is a setting an operator turns on once that is true.
"""

from collections.abc import Awaitable, Callable
from typing import Final

from fastapi import FastAPI, Request, Response

# `'unsafe-eval'` is required by Datastar, which compiles `data-*` expressions with the `Function`
# constructor (ADR-012, and docs/operations.md records the review of that grant). Everything else
# stays closed: no third-party origin may supply a script, style, image, font, or connection; the
# page cannot be framed; a form cannot post off-site. `'unsafe-inline'` is deliberately *not*
# granted, so an injected `<script>` tag or inline handler is still refused.
CONTENT_SECURITY_POLICY: Final = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self' 'unsafe-eval'",
        "style-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "object-src 'none'",
    )
)

DEFAULT_HSTS_MAX_AGE_SECONDS: Final = 31_536_000  # one year

SECURITY_HEADERS: Final = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # The site has no cross-origin API and no reason to be embedded.
    "Cross-Origin-Opener-Policy": "same-origin",
    "X-Frame-Options": "DENY",
}


def strict_transport_security(max_age_seconds: int) -> str:
    """The HSTS value for a max-age.

    `preload` is deliberately never emitted: submitting to the preload list is a decision with a
    slow exit, and it is not one a configuration default should make for an operator.
    """
    return f"max-age={max_age_seconds}; includeSubDomains"


def install_security_headers(app: FastAPI, *, hsts_max_age_seconds: int = 0) -> None:
    headers = dict(SECURITY_HEADERS)
    if hsts_max_age_seconds > 0:
        headers["Strict-Transport-Security"] = strict_transport_security(hsts_max_age_seconds)

    @app.middleware("http")
    async def add_security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for header, value in headers.items():
            # A route that has deliberately set its own value keeps it; the archived-document
            # route, for instance, sets its own caching and robots headers.
            response.headers.setdefault(header, value)
        return response
