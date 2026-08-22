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
    assert extras == {"s3"}, "a new extra needs a decision about whether it ships"

    sync = re.search(r"uv sync[^\n]*", DOCKERFILE)
    assert sync is not None
    installed = set(re.findall(r"--extra (\S+)", sync.group(0)))

    if documented("BLOB_STORAGE_BACKEND") == "s3":
        assert "s3" in installed, ".env.example selects the s3 backend; the image must install it"
    # RAG is off by default and its OpenAI-compatible adapter uses the base HTTP dependency.
    assert documented("RAG_ENABLED") == "false"


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


def test_the_shipped_template_cannot_drift_into_an_on_by_default_corpus() -> None:
    """A mirrored corpus cannot be withdrawn (ADR-018), so the shipped default is the decision.

    The validator in `config.py` catches an operator who enables serving without the rights
    confirmation. It cannot catch a template that hands them a configuration already enabling it,
    because they would then have both — which is why this is asserted against the file itself.
    """
    assert documented("SERVE_LEGISLATION_CORPUS") == "false"
    assert documented("LEGISLATION_PUBLICATION_MODE") == "metadata"
    assert documented("LEGISLATION_CORPUS_RIGHTS_CONFIRMED") == "false"


def test_the_app_can_read_the_pipeline_store_it_is_configured_to_serve() -> None:
    """`PIPELINE_DATA_ROOT` is the corpus's only copy; without a mount the app serves nothing.

    Nothing in the test suite would notice: every pipeline test builds its store under `tmp_path`.
    The container is `read_only: true`, so an unmounted path is not even a directory the app could
    fall back to creating — the corpus routes would answer 404 for a corpus that exists on disk.
    """
    app = COMPOSE[COMPOSE.index("  app:") : COMPOSE.index("  worker:")]
    root = documented("PIPELINE_DATA_ROOT")
    assert root, ".env.example must document where the pipeline store lives"
    # Read-only, because the app serves the corpus (ADR-018) and never writes it: a writable mount
    # would let a request path reach the one store in the stack that nothing can rebuild.
    assert f"pipeline_data:{root}:ro" in app, "the app must mount the pipeline store, read-only"
    # Declared as a named volume, or compose refuses to start the stack at all.
    assert re.search(r"^volumes:$.*^  pipeline_data:$", COMPOSE, re.M | re.S)


def test_the_vendored_akn_schemas_ship_inside_the_package() -> None:
    """The runtime stage copies only the virtualenv, so anything outside `src/billwatcher` is gone.

    `pipeline.akn_schema` validates every emitted document against these files and raises when it
    cannot. Kept vendored rather than fetched: validation must not depend on an OASIS host being up,
    and the digests in the README are what makes "schema-valid" mean a specific schema.
    """
    schemas = Path("src/billwatcher/pipeline/schemas")
    assert (schemas / "akomantoso30.xsd").is_file()
    # akomantoso30.xsd imports the XML namespace schema; without it the build fails at import time.
    assert (schemas / "xml.xsd").is_file()
    assert (schemas / "README.md").is_file(), "a vendored copy needs its provenance and digests"

    packaged = PYPROJECT["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert packaged == ["src/billwatcher"]
    # The runtime image installs the wheel and copies nothing else from the source tree.
    assert "COPY --from=builder" in DOCKERFILE
    assert not re.search(r"^COPY[^\n]*\bsrc\b", DOCKERFILE[DOCKERFILE.index("AS runtime") :], re.M)
