"""Shared fixtures.

The offline suite runs entirely on SQLite. PostgreSQL-only behaviour (the weighted tsvector,
`websearch_to_tsquery`, `ts_headline`, and pgvector) is exercised only when a disposable test
database is supplied through BILLWATCHER_TEST_DATABASE_URL, and skips with a clear message
otherwise.
"""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text

POSTGRES_URL_ENV = "BILLWATCHER_TEST_DATABASE_URL"


def postgres_url() -> str | None:
    return os.environ.get(POSTGRES_URL_ENV) or None


@pytest.fixture(scope="session")
def postgres_engine() -> Iterator[Engine]:
    url = postgres_url()
    if not url:
        pytest.skip(f"set {POSTGRES_URL_ENV} to a disposable database to run PostgreSQL tests")
    engine = create_engine(url, poolclass=None)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    _upgrade_to_head(url)
    yield engine
    engine.dispose()


def _upgrade_to_head(url: str) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config("alembic.ini")
    config.attributes["connection_url"] = url
    command.upgrade(config, "head")
