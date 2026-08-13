from datetime import date, datetime, timedelta, timezone


def ensure_utc(value: datetime) -> datetime:
    """Every DateTime column in this app is declared `DateTime(timezone=True)` and
    every value written to one is already UTC-aware (`datetime.now(timezone.utc)`).
    Postgres round-trips that faithfully, but SQLite (the integration test suite's
    stand-in DB) silently drops the tzinfo on read regardless of the column's
    `timezone=True` -- a value freshly read back from the DB can come back naive even
    though it was written aware. Comparing that naive value against a fresh
    `datetime.now(timezone.utc)` then raises `TypeError: can't compare offset-naive
    and offset-aware datetimes`. Call this on any DB-sourced datetime before comparing
    it against "now" -- a no-op against Postgres (already aware), and correct against
    SQLite (naive values here are always UTC, since that's the only thing this app
    ever writes)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def month_range(start: date, end: date) -> list[date]:
    """Every month-start date from start's month through end's month, inclusive."""
    months = []
    cursor = start.replace(day=1)
    end_marker = end.replace(day=1)
    while cursor <= end_marker:
        months.append(cursor)
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    return months
