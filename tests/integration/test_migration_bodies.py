"""Migration bodies must actually run, which upgrading an empty database never proves.

Both 0003 and 0004 carried this defect; 0004 was found first (`docs/status.md`, 2026-08-19).

Migration 0001 calls `Base.metadata.create_all()`, so on a fresh database every later migration
finds its tables already present and skips its own DDL. `alembic upgrade head` therefore passes
while a migration body is broken, and the only deployment that ever executes that body is a real
one that reached the previous revision before the change landed.

The failure this catches is specific and silent: a foreign-key column declared as
`sa.Column("x", sa.ForeignKey(...))` with no type compiles to `NullType` inside a migration —
Alembic builds each table in its own metadata, so there is no referenced column to infer from —
and raises `CompileError` at upgrade time.
"""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

# The tables migration 0004 creates. Extend this as later migrations add their own; 0002 and 0003
# are deliberately absent, because their bodies carry the untyped-foreign-key defect this test
# exists to catch and fixing them is recorded as its own work item (TODO.md).
MIGRATION_TABLES = {
    "0003": ("document_chunks", "chunk_embeddings"),
    "0004": ("provision_nodes", "document_structures"),
}


def _upgrade(url: str, revision: str) -> None:
    config = Config("alembic.ini")
    config.attributes["connection_url"] = url
    command.upgrade(config, revision)


@pytest.mark.parametrize(("revision", "tables"), sorted(MIGRATION_TABLES.items()))
def test_a_migration_body_runs_against_a_database_that_predates_it(
    tmp_path: Path, revision: str, tables: tuple[str, ...]
) -> None:
    database = tmp_path / "migration.db"
    url = f"sqlite+pysqlite:///{database}"
    previous = f"{int(revision) - 1:04d}"

    _upgrade(url, previous)
    # Simulate a database that genuinely reached the previous revision before this change: the
    # tables the new migration creates do not exist yet.
    with sqlite3.connect(database) as connection:
        for table in tables:
            connection.execute(f"DROP TABLE IF EXISTS {table}")

    _upgrade(url, revision)

    with sqlite3.connect(database) as connection:
        created = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert set(tables) <= created


def test_the_migration_names_its_objects_the_way_create_all_does(tmp_path: Path) -> None:
    """A database built fresh and one upgraded in place must carry the same object names.

    Otherwise a later migration that alters a constraint by name works on half the fleet.
    """
    from sqlalchemy import create_engine, inspect

    import billwatcher.models  # noqa: F401  -- importing the models is what populates the metadata
    from billwatcher.db import Base

    fresh = create_engine(f"sqlite+pysqlite:///{tmp_path / 'fresh.db'}")
    Base.metadata.create_all(fresh)

    upgraded_path = tmp_path / "upgraded.db"
    url = f"sqlite+pysqlite:///{upgraded_path}"
    _upgrade(url, "0003")
    with sqlite3.connect(upgraded_path) as connection:
        for table in MIGRATION_TABLES["0004"]:
            connection.execute(f"DROP TABLE IF EXISTS {table}")
    _upgrade(url, "0004")

    upgraded = create_engine(url)
    for table in ("document_structures", "provision_nodes"):
        fresh_indexes = {index["name"] for index in inspect(fresh).get_indexes(table)}
        upgraded_indexes = {index["name"] for index in inspect(upgraded).get_indexes(table)}
        assert fresh_indexes, f"{table} declares no index, so this comparison proves nothing"
        assert fresh_indexes == upgraded_indexes, table
        # Unique constraints are left unnamed for the backend to name, as 0003 does, so compare
        # the columns they cover rather than names SQLite does not report.
        fresh_unique = {
            tuple(unique["column_names"])
            for unique in inspect(fresh).get_unique_constraints(table)
        }
        upgraded_unique = {
            tuple(unique["column_names"])
            for unique in inspect(upgraded).get_unique_constraints(table)
        }
        assert fresh_unique == upgraded_unique, table
