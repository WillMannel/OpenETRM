"""Lineage helpers for risk/valuation results: what code produced a given persisted
number, so it can be explained (or proven to have changed) later -- see
ARCHITECTURE.md's "Risk reproducibility and lineage" section for the full design
(this is the code-version piece; trade/market-data snapshotting lives alongside each
result's own persistence code, not here).
"""

import os
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version


@lru_cache
def get_code_version() -> str:
    """A `GIT_SHA`/`GIT_COMMIT` env var (set by CI/the deploy pipeline, if either is
    configured) takes precedence -- it's the most precise answer to "what code
    produced this number," since it pins the exact commit rather than a version
    string that only changes on a release. Falls back to the installed package
    version (`pyproject.toml`'s `version`), and `"unknown"` if even that can't be
    determined (e.g. running from a source checkout that was never `pip install`'d).
    Cached -- this can't change during a running process's lifetime."""
    git_sha = os.environ.get("GIT_SHA") or os.environ.get("GIT_COMMIT")
    if git_sha:
        return git_sha
    try:
        return version("openetrm-backend")
    except PackageNotFoundError:
        return "unknown"
