# Operations runbook

## Configuration and secrets

Copy .env.example to a mode-restricted .env, replace every placeholder, and use a generated database
password. Production startup rejects placeholder domains, contacts, and credentials. Never commit
.env. SCRAPE_ENABLED=false is the safe initial state.

## Fresh deployment

1. Provision current Docker Engine/Compose, persistent disk, outbound HTTPS, DNS, and inbound ports
   80/443 only.
2. Configure .env and run make docker-build.
3. Run make compose-up. The database must be healthy and the one-shot migration must reach head
   before app and worker start.
4. Keep crawling disabled. Verify health, status, browse/search, canonical links, and external HTTPS.
5. Record dependency/container review and live crawl approval in docs/status.md.
6. Save current robots evidence and run one low-rate approved full crawl.
7. Review counts/anomalies; require make doctor and make verify-storage before publication.

PostgreSQL has no host-published port. Caddy is the only public service. The app blob mount is
read-only and the worker mount is read-write. Do not add source bind mounts in production.

## Migrations

make migrate upgrades to Alembic head. Compose runs it once. Production downgrades are unsupported
because they destroy archival tables; recover using tested database and blob backups. Never let web
replicas race to migrate.

## Routine operation

- make status reports coverage, queue state, latest run, and pipeline versions.
- make doctor fails on critical anomalies, invalid current versions, or corrupt blobs.
- make logs follows bounded app and worker logs.
- make reparse and make reextract are dry runs unless ARGS=--apply is provided.
- make prune-blobs is dry-run-first and only ref-count-zero blobs are eligible.

Monitor readiness, each target's last success, run duration/outcome, count/structure anomalies,
queue depth/dead letters, extraction backlog, disk/database/blob growth, response errors, and search
latency.

## Backup and restore

Database and blob backups form one recovery set. Run make backup with an explicit BACKUP_DIR and
make backup-blobs with an explicit BLOB_BACKUP_DEST. Store them outside the deployment host,
checksum and encrypt them, restrict access, and use a reviewed retention policy.

For a restore drill, use an isolated deployment, stop writes, restore the database with
CONFIRM_RESTORE=yes and explicit RESTORE_PATH, restore the blob tree, migrate to head, then run
make verify-storage and make doctor. Verify representative old/current versions, extractions,
search, bill pages, coverage history, and hashes. Record date, operator, backup IDs, duration, and
outcome in the manual gate log. A database-only restore is a failed restore.

## Live crawling and incidents

Every crawl preflights root robots.txt with strict TLS. A changed hash or denial withholds the run.
Never disable certificate verification. Failures use bounded retry/circuit behavior; budget
exhaustion leaves queue work resumable.

For structure drift, count collapse, quarantined PDF, or robots changes: preserve the snapshot,
leave prior data live, investigate before acknowledgment, add upstream evidence, and replay stored
bytes after correcting the parser.

## Retention

- document versions, bill events, record changes, and presence observations: indefinite;
- source snapshot rows: indefinite; content deduplicates by hash;
- fetch attempts: default 180 days, aggregate before explicit deletion;
- extractions: current and previous versions, older only by reviewed job;
- embeddings: explicit removal after replacement validation.

## External release checklist

Confirm valid HTTPS and redirects, certificate persistence, canonical URL, sitemap, source links,
no-JavaScript/mobile behavior, status freshness, readiness, restore drill, non-root image, internal
database, read-only app blob access, vulnerability/dependency reviews, and real contact identity.
