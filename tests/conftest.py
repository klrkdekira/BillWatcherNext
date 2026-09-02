"""Shared fixtures.

The whole suite is offline: no database, no object store, no network, no model endpoint. What is
left to isolate is the developer's own environment, which is exactly what the two fixtures below
do.
"""

from pathlib import Path

import pytest

from billwatcher.config import Settings, get_settings


def _environment_variables() -> tuple[str, ...]:
    """Every `Settings` field, as the environment variable that sets it.

    Derived rather than listed. A hand-maintained list needed its own guard test to catch a new
    field that nobody had added to it, and that guard could only ever fail *after* a setting had
    already leaked into a test run. Deriving removes the drift and the guard together.
    """
    return tuple(name.upper() for name in Settings.model_fields)


# Settings whose default is a path *relative to the working directory*, which in a test run is the
# repository itself. Unsetting them is not enough: a test that reaches a step which writes would
# then write into the developer's real `corpus/` or, worse, into `docs/` — the committed, published
# tree. One did exactly that, leaving a full 194-file publication in the working tree. Every run
# now gets its own throwaway roots, so the accident is structurally impossible rather than avoided
# by each test remembering to redirect them.
_WRITABLE_ROOTS = ("CORPUS_ROOT", "SITE_ROOT")


@pytest.fixture(autouse=True)
def isolate_settings_from_the_local_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Tests must describe their own configuration, never inherit the developer's.

    Without this a populated .env silently changes what a test asserts — a suite that passes on one
    machine and fails on another.
    """
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in _environment_variables():
        monkeypatch.delenv(name, raising=False)
    for name in _WRITABLE_ROOTS:
        monkeypatch.setenv(name, str(tmp_path / "roots" / name.lower()))
    get_settings.cache_clear()
