"""Shared response shapes for the async (Arq-backed) job endpoints -- one enqueue
response and one status/result response, reused by market_data and risk routers."""

from typing import Any

from pydantic import BaseModel


class JobEnqueuedRead(BaseModel):
    job_id: str


class JobStatusRead(BaseModel):
    job_id: str
    status: str
    result: Any | None = None
