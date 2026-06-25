FROM python:3.12-slim

# Set environment variables to prevent Python from writing .pyc files and to ensure that output is not buffered
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv

WORKDIR /workspace

COPY pyproject.toml /workspace/pyproject.toml
COPY apps/api /workspace/apps/api
RUN uv sync --no-dev

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "--app-dir", "apps/api", "orbika_console_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
