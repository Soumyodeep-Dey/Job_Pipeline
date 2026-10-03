FROM python:3.12-slim
WORKDIR /code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home appuser
COPY app ./app
COPY tests ./tests
COPY migrations ./migrations
COPY alembic.ini .
USER appuser
EXPOSE 8000
CMD ["sh", "-c", "python -m app.migrate && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log --no-proxy-headers"]
