from datetime import date, timedelta


def month_range(start: date, end: date) -> list[date]:
    """Every month-start date from start's month through end's month, inclusive."""
    months = []
    cursor = start.replace(day=1)
    end_marker = end.replace(day=1)
    while cursor <= end_marker:
        months.append(cursor)
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    return months
