# Data model notes

The authoritative schema is the Alembic migration and SQLAlchemy mappings.

Bill event fingerprints are SHA-256 over the stable serialization of bill ID, chamber, event type,
start/end dates, sequence, normalized source label, and normalized source value. Run, snapshot, and
observation timestamps are deliberately excluded so replay is idempotent. Search units are owned
by application services and updated in the same transaction as their source write; database
triggers do not maintain them.
