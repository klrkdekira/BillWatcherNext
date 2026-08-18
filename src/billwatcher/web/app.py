"""Application factory.

The factory owns exactly three things: the template mount, the provider wiring, and route
registration. Everything else lives in `routes.py`, `schemas.py`, and `retrieval.py`.
"""

from collections.abc import Callable

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from billwatcher.config import Settings, get_settings
from billwatcher.db import SessionLocal
from billwatcher.version import __version__
from billwatcher.web.retrieval import build_retrieval
from billwatcher.web.routes import register_routes
from billwatcher.web.templating import PACKAGE_DIR


def create_app(
    session_factory: Callable[[], Session] = SessionLocal,
    settings: Settings | None = None,
) -> FastAPI:
    app = FastAPI(title="BillWatcherNext", version=__version__)
    app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")
    config = settings or get_settings()
    register_routes(
        app,
        session_factory=session_factory,
        config=config,
        retrieval=build_retrieval(config),
    )
    return app


app = create_app()
