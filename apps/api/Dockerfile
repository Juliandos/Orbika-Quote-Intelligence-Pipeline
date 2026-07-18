FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir uv
WORKDIR /workspace
COPY pyproject.toml uv.lock ./
COPY apps/api ./apps/api
COPY tools ./tools
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --no-dev --frozen || uv sync --no-dev
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "--app-dir", "apps/api", "orbika_console_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
