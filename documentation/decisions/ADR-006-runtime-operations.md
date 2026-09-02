# ADR-006: Runtime scheduler, locks, search ownership, and alert delivery

Status: accepted
Date: 2026-08-17

Use the long-running worker loop with configured intervals and bounded plus-or-minus five-percent
jitter without catch-up bursts. Overlap is prevented by PostgreSQL
advisory key 0x42494C4C. Backfills use distinct key 0x4241434B. Fetch leases default to ten minutes
and five attempts. Search units are application-owned and rebuilt transactionally, never split
between triggers and application code. Release 1 alert delivery is the anomaly table plus public
status and non-zero make doctor; a push channel remains a production-host decision.
