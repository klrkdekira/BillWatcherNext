"""The shipped image must be able to run the configuration the project documents.

`.env.example` and `compose.yaml` select the VersityGW S3 backend (ADR-013), but the Dockerfile
installed only the base dependencies, so the production-shaped stack exited on start with "the S3
archive backend needs the 's3' dependency group installed". Every test passed: nothing compared the
documented configuration against the image's dependency set. These are static checks, so they cost
nothing and catch that class of drift.
"""

import re
import tomllib
from pathlib import Path

DOCKERFILE = Path("Dockerfile").read_text()
ENV_EXAMPLE = Path(".env.example").read_text()
COMPOSE = Path("compose.yaml").read_text()
PYPROJECT = tomllib.loads(Path("pyproject.toml").read_text())


def documented(name: str) -> str | None:
    match = re.search(rf"^{name}=(.*)$", ENV_EXAMPLE, re.M)
    return match.group(1).strip() if match else None


def test_the_image_installs_the_extras_the_documented_configuration_needs() -> None:
    extras = set(PYPROJECT["project"]["optional-dependencies"])
    assert extras == {"rag", "s3"}, "a new extra needs a decision about whether it ships"

    sync = re.search(r"uv sync[^\n]*", DOCKERFILE)
    assert sync is not None
    installed = set(re.findall(r"--extra (\S+)", sync.group(0)))

    if documented("BLOB_STORAGE_BACKEND") == "s3":
        assert "s3" in installed, ".env.example selects the s3 backend; the image must install it"
    # RAG is off by default, so its SDK deliberately stays out of the image.
    assert documented("RAG_ENABLED") == "false"
    assert "rag" not in installed


def test_the_locked_dependencies_are_installed_from_the_lockfile() -> None:
    """A build that resolves fresh is not the build that was audited."""
    assert "--locked" in DOCKERFILE
    assert Path("uv.lock").exists()


def test_the_base_image_is_pinned_by_digest() -> None:
    """A re-pushed tag would change the image without changing the repository."""
    bases = re.findall(r"^FROM (\S+)", DOCKERFILE, re.M)
    assert bases, "no FROM lines found"
    for base in bases:
        assert "@sha256:" in base, f"{base} is pinned by tag only"
    # Both stages must use the same base, or the runtime is not what was built against.
    assert len(set(bases)) == 1


def test_the_image_runs_as_a_non_root_uid_matching_the_volume_owner() -> None:
    assert re.search(r"^USER 10001:10001$", DOCKERFILE, re.M)
    assert "--uid 10001" in DOCKERFILE
    # compose mounts the blob volume for the same uid; a mismatch silently breaks writes.
    assert "10001" in COMPOSE or "billwatcher" in COMPOSE


def test_the_stack_ships_no_tls_terminator_and_publishes_an_origin_for_one() -> None:
    """TLS is terminated by a proxy outside this repository (ADR-015).

    Two things have to stay true together: nothing here terminates TLS, and the app is reachable
    for the thing that does — bound to loopback, because an unencrypted origin on 0.0.0.0 is how a
    reverse-proxy deployment accidentally serves plaintext to the network.
    """
    assert not Path("Caddyfile").exists()
    assert "caddy" not in COMPOSE.lower()
    assert '"127.0.0.1:8000:8000"' in COMPOSE
    # The database and the blob gateway stay off the published surface entirely.
    assert "internal: true" in COMPOSE


def test_the_crawler_can_reach_the_internet() -> None:
    """An internal-only network lets the worker start, look healthy, and fail every fetch."""
    worker = COMPOSE[COMPOSE.index("  worker:") :]
    worker = worker[: worker.index("\nnetworks:")]
    assert "egress" in worker, "the worker crawls Parliament and needs outbound access"
