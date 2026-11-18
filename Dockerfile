FROM python:3.12-slim AS base
WORKDIR /code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home appuser
FROM base AS sender
USER root
RUN pip install --no-cache-dir playwright==1.55.0 && apt-get update && apt-get install -y --no-install-recommends chromium && rm -rf /var/lib/apt/lists/*
COPY app ./app
COPY tests ./tests
COPY migrations ./migrations
COPY alembic.ini .
USER appuser
CMD ["python", "-m", "app.sender"]

FROM base AS runtime
COPY app ./app
COPY tests ./tests
COPY migrations ./migrations
COPY alembic.ini .
USER appuser
EXPOSE 8000
CMD ["sh", "-c", "python -m app.migrate && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log --no-proxy-headers"]
