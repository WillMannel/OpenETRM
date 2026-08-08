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


def rows_to_response(
    rows: list[dict[str, Any]], export_format: ExportFormat, filename_stem: str
) -> Response:
    df = pd.DataFrame(rows)

    if export_format == "csv":
        buf = io.StringIO()
        df.to_csv(buf, index=False)
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
