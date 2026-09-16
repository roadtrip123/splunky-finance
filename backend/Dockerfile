FROM ghcr.io/astral-sh/uv:0.9.24 AS uv
FROM python:3.12.12-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
RUN groupadd --gid 10001 bank && useradd --uid 10001 --gid bank --create-home bank
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend/app ./app
COPY data /app/data
RUN mkdir /app/runtime && chown bank:bank /app/runtime
USER bank
ENV PATH="/app/backend/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
