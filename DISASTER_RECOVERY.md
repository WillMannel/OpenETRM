# Disaster recovery: backup, restore, RTO/RPO

Backup/restore runbook for task P1-10 ("Production operability, DR, and security
review" — see `ARCHITECTURE.md`'s section of the same name). Every step below has
actually been run end to end via `backend/scripts/dr_backup_restore_drill.py`, not
just written down — see "The drill" for what that script proves and what it
doesn't. A DR plan nobody has ever executed is a document, not a plan.

## What actually needs backing up

| Store | Backup? | Why |
|---|---|---|
| **Postgres** (`trades`, `books`, `counterparties`, `valuation_runs`, `var_results`, `sensitivity_results`, `stress_results`, `option_greeks_results`, `limit_breaches`, `audit_events`, `users`, `refresh_tokens`, `api_keys`, `market_data_points`, ...) | **Yes** | The entire system of record. Trade capture, valuation/risk history and its lineage (task P1-8), the audit trail, and auth all live here. Losing it is losing the business. |
| **Redis** (revoked-token denylist, refresh-token-reuse detection, login rate-limit counters, Arq job queue) | **No** | Every use of Redis in this codebase is either a short-TTL cache (denylist entries expire with the token they revoke) or ephemeral operational state (rate-limit counters, in-flight job queue). Losing it on restart degrades gracefully: a cleared denylist just means already-revoked tokens work again until their natural JWT expiry (bounded, short-lived by design), a cleared job queue means in-flight background jobs need re-triggering, and a cleared rate limiter just resets attempt counts. Nothing here is a system of record; nothing here needs to survive a disaster. |

This asymmetry is deliberate, not an oversight — see `ARCHITECTURE.md`'s "Enterprise
SSO, token refresh & revocation" section for why revocation state was designed to be
safe to lose in the first place.

## Backup strategy

Two layers, standard for a Postgres-backed OLTP system:

1. **Continuous WAL archiving** (`archive_mode = on` + `archive_command` shipping to
   object storage, or a managed provider's continuous-backup feature — e.g. RDS/Cloud
   SQL automated backups, or `pgBackRest`/`wal-g` self-managed) — this is what makes
   point-in-time recovery possible and bounds RPO to roughly the WAL-shipping
   interval, not "since last night's dump."
2. **Daily `pg_dump` full logical backup**, retained on a rolling window (e.g. 14
   daily + 12 monthly) — a full logical dump is a second, independent recovery path
   from WAL archiving (different failure mode: a corrupted WAL stream doesn't also
   corrupt yesterday's dump), and it's what this repo's drill script exercises.

Neither of these is wired up as infrastructure in this repo — there's no managed
Postgres provider or object-storage target to configure them against yet (see
`ARCHITECTURE.md`'s "Chosen stack": Docker Compose is the only deployment target
today). What *is* here is the runbook and a proven mechanism, so standing up either
layer against a real target is "point it at the provider," not "figure out the
commands from scratch."

## RTO / RPO targets

| | Target | Basis |
|---|---|---|
| **RPO** (max acceptable data loss) | ~5 minutes with WAL archiving configured; ~24h on daily `pg_dump` alone | WAL-shipping interval is operator-configurable (typically continuous or ~1 min segments); daily-dump-only means losing up to a full day if the disaster hits right before the next dump. |
| **RTO** (max acceptable time to restore service) | To be set once running against real production data volumes and real backup-storage transfer speed — **not** claimed here. See "What the drill does and doesn't prove" below for why a number from this sandbox would be dishonest. |

## The runbook

```bash
# 1. Backup (run on a schedule -- cron/systemd timer/managed-provider equivalent):
pg_dump --format=custom --file=openetrm-$(date +%Y%m%d-%H%M%S).dump \
    "$DATABASE_URL_SYNC"   # postgresql://... -- pg_dump doesn't take the +asyncpg driver suffix
# ship the resulting file to off-host/off-region storage; a backup that lives on
# the same disk as the database isn't a disaster-recovery backup.

# 2. Restore (disaster response):
createdb openetrm_restored   # or drop/recreate the target if restoring in place
pg_restore --dbname=postgresql://user:pass@host/openetrm_restored --no-owner \
    openetrm-<timestamp>.dump

# 3. Verify before cutting over -- row counts at minimum, ideally a smoke test
# against the restored DB (e.g. GET /health/ready pointed at it, or a read-only
# query against a few known trades) before repointing DATABASE_URL at it for real.

# 4. Redis needs no restore step -- see "What actually needs backing up" above.
# Just start a fresh instance; the application tolerates an empty one.
```

## The drill

`backend/scripts/dr_backup_restore_drill.py` runs the actual mechanism end to end
against a real (scratch) Postgres database: seeds a `Counterparty`/`Book`/`Trade`
(including an exact `Decimal` fixed price, specifically to prove numeric precision
survives the round trip — see task P1-7's Decimal-money work), `pg_dump`s it,
**drops the database entirely** (a real simulated loss, not a copy-and-compare),
`pg_restore`s from the dump into a freshly recreated empty database, and asserts the
restored data matches the pre-loss snapshot exactly. It also times the backup and
restore steps and reports the dump size.

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://openetrm:openetrm@localhost:5432/openetrm \
    python scripts/dr_backup_restore_drill.py
```

Last run in this sandbox: backup 0.28s / restore 0.23s for a 50 KB dump (3 rows).
Recommended cadence for a real deployment: quarterly, or whenever the backup/restore
tooling or Postgres major version changes.

### What the drill does and doesn't prove

**Proves**: the backup file format is restorable, the restore process doesn't
silently drop or corrupt rows, and `Decimal`-precision trade economics survive the
round trip byte-for-byte (a `Decimal`-to-`float`-and-back bug here would be exactly
the kind of silent corruption task P1-7 was about eliminating from the *live* code
path — this confirms the backup path doesn't reintroduce it).

**Doesn't prove** (tracked in `FUTURE_WORK.md`):
- **Timing at production scale.** 3 rows tells you nothing about RTO for the
  50,000-trade portfolios `PERFORMANCE.md` benchmarks against — `pg_dump`/
  `pg_restore` wall-clock time scales with data volume and is bound by
  backup-storage transfer speed in a real environment, neither of which this
  sandbox can represent honestly. Re-run this drill's timing against a realistically
  sized database (e.g. seeded via `benchmark_scale.py`) before publishing a real RTO
  number.
- **Cross-server restore.** This drill restores onto the same Postgres server the
  backup was taken from. A real disaster (host loss, region loss) means restoring
  onto a *different* server — untested here, and the one gap in this drill that
  most needs closing before relying on this runbook for a real incident.
- **TimescaleDB hypertable restore.** `market_data_points` is a real hypertable in
  production; this sandbox has no `timescaledb` extension (the same limitation
  documented in `PERFORMANCE.md` and this repo's migration-validation scripts), so
  the drill builds a plain-table schema instead of running the real Alembic
  migrations. Timescale ships `pg_dump`/`pg_restore`-compatible hooks for
  hypertables specifically so this isn't expected to behave differently, but that
  claim is unverified here, not proven.
- **WAL-archiving / point-in-time recovery.** The drill exercises the full-`pg_dump`
  path only; PITR restore-to-a-specific-timestamp is a different mechanism
  (`pg_basebackup` + WAL replay) not exercised at all here, since there's no
  WAL-archiving infrastructure configured in this repo to drill against (see
  "Backup strategy" above).
