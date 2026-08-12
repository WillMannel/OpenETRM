"""app.common.dates.ensure_utc: guards against the SQLite-drops-tzinfo-on-read
footgun (see its docstring) that broke refresh-token expiry comparisons under the
integration test suite -- a naive datetime read back from a `DateTime(timezone=True)`
column must be treated as UTC, since that's the only thing this app ever writes to
one."""

from datetime import datetime, timezone

from app.common.dates import ensure_utc


def test_ensure_utc_leaves_an_already_aware_datetime_unchanged():
    aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert ensure_utc(aware) is aware


def test_ensure_utc_attaches_utc_to_a_naive_datetime():
    naive = datetime(2026, 1, 1, 12, 0, 0)
    result = ensure_utc(naive)
    assert result.tzinfo == timezone.utc
    assert result.replace(tzinfo=None) == naive


def test_ensure_utc_result_is_comparable_to_a_timezone_aware_now():
    naive = datetime(2020, 1, 1)  # far enough in the past to be unambiguously expired
    assert ensure_utc(naive) <= datetime.now(timezone.utc)
