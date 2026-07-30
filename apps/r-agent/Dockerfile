ARG PYTHON_IMAGE=python:3.12.11-slim-bookworm
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.19

FROM ${UV_IMAGE} AS uv_source
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH=/app/.venv/bin:$PATH

COPY --from=uv_source /uv /uvx /usr/local/bin/
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

RUN groupadd --gid 10001 higgs \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin higgs \
    && mkdir -p /app/data \
    && chown -R higgs:higgs /app/data

USER higgs
CMD ["python", "-m", "r_agent.phase2_cli", "listen"]