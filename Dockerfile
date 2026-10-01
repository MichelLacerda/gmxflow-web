FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends gromacs ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
WORKDIR /app
COPY gmxflow /app/gmxflow
COPY gmxflow-web/pyproject.toml gmxflow-web/uv.lock /app/gmxflow-web/
COPY gmxflow-web/gmxflow_web /app/gmxflow-web/gmxflow_web
WORKDIR /app/gmxflow-web
RUN uv sync --locked --no-dev
ENV PATH="/app/gmxflow-web/.venv/bin:$PATH" PYTHONUNBUFFERED=1 DATABASE=/data/web.sqlite3 PROJECT_ROOT=/data/projects
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "flask", "--app", "gmxflow_web:create_app", "run", "--host", "0.0.0.0", "--port", "8000"]
