"""Application factory.

The factory owns exactly four things: the security headers, the template mount, the provider
wiring, and route registration. Everything else lives in `routes.py`, `schemas.py`, and
`retrieval.py`.
"""

from collections.abc import Callable

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from billwatcher.config import Settings, get_settings
from billwatcher.db import SessionLocal
from billwatcher.pipeline.store import build_pipeline_store
from billwatcher.version import __version__
from billwatcher.web.corpus import register_corpus_routes
from billwatcher.web.retrieval import build_retrieval
from billwatcher.web.routes import register_routes
from billwatcher.web.security_headers import install_security_headers
from billwatcher.web.templating import PACKAGE_DIR


def create_app(
    session_factory: Callable[[], Session] = SessionLocal,
    settings: Settings | None = None,
) -> FastAPI:
    app = FastAPI(title="BillWatcherNext", version=__version__)
    config = settings or get_settings()
    install_security_headers(app, hsts_max_age_seconds=config.hsts_max_age_seconds)
    app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")
    register_routes(
        app,
        session_factory=session_factory,
        config=config,
        retrieval=build_retrieval(config),
    )
    # Registered even when SERVE_LEGISLATION_CORPUS is off: the routes answer with the publication
    # policy rather than a bare 404, so a reader following a citation is told why (ADR-018).
    register_corpus_routes(app, store=build_pipeline_store(config), config=config)
    return app


app = create_app()
