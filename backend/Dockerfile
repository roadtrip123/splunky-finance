FROM ghcr.io/astral-sh/uv:0.9.24 AS uv
FROM python:3.12.12-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
RUN groupadd --gid 10001 bank && useradd --uid 10001 --gid bank --create-home bank
WORKDIR /app/backend
# Any PEM dropped into backend/ca/ is trusted for the dependency download. Empty on a normal
# network; needed behind a TLS-intercepting proxy, where the host trusts the substituted CA but
# this container does not. UV_NATIVE_TLS makes uv read the platform store rather than its own
# bundled roots, so update-ca-certificates is enough to make it work.
COPY backend/ca/ /usr/local/share/ca-certificates/
# Report what was added, because a silent no-op here looks identical to a proxy that is not
# trusted, and the next failure is thirty lines further down in uv's output.
RUN update-ca-certificates --verbose 2>&1 | tail -2
# Point uv at the regenerated bundle explicitly. update-ca-certificates only hash-links the first
# certificate of a multi-certificate file, so relying on the directory lookup is not enough when
# the file copied in is a whole host trust store.
ENV UV_NATIVE_TLS=1 SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY --chown=bank:bank backend/app ./app
COPY --chown=bank:bank data /app/data
RUN mkdir /app/runtime && chown bank:bank /app/runtime
USER bank
# The release this image was built from. `.git` is excluded from the build context, so it has to be
# passed in; scripts/selfupdate.py does that automatically. Empty on a build that did not bother, and
# the portal then falls back to the host's state file, or reports the version as unknown.
ARG APP_VERSION=""
ENV APP_VERSION=${APP_VERSION}
ENV PATH="/app/backend/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
