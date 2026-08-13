# Shared by both the `api` and `worker` docker-compose services (and any real
# deployment of either) -- same dependency set, different CMD/command override.
# Multi-stage: build-essential (a C toolchain, needed to build some dependencies'
# native extensions) never makes it into the final image, keeping the deployed
# image smaller and its attack surface closer to "just the interpreter + app".
FROM python:3.11-slim AS builder
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
# Upgrade pip/setuptools/wheel first -- `python -m venv` bootstraps whatever
# versions shipped with this base image, not necessarily patched against the
# latest advisories (caught by this image's own Trivy scan in CI: a stale
# bundled setuptools/wheel pulled in jaraco.context 5.3.0 and wheel 0.45.1,
# both with fixed HIGH-severity CVEs -- CVE-2026-23949, CVE-2026-24049).
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --no-cache-dir .

FROM python:3.11-slim
WORKDIR /app

# curl: used only by this image's own HEALTHCHECK below (the `api` service's --
# the `worker` service has no HTTP endpoint to probe and disables the inherited
# HEALTHCHECK in docker-compose.yml instead of this being wasted on it).
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app
ENV PATH="/opt/venv/bin:$PATH"

USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
