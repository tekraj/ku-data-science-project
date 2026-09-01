# Build context MUST be the repo root, e.g.:
#   docker build -f scraper-service/Dockerfile -t scraper-service .
FROM python:3.11-slim

# Without this, Python fully block-buffers stdout when it isn't a TTY (true
# inside a container), so `docker logs` / `docker-compose logs` can sit
# silent for minutes at a time even while the worker is actively processing
# -- confirmed directly: real backfill progress (rows landing in
# historical_backfill_urls) was happening with zero corresponding log
# output visible.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install the shared nepse-common package first so its layer is cached
# independently of scraper-service source changes.
COPY nepse-common /nepse-common
RUN pip install --no-cache-dir -e /nepse-common

COPY scraper-service /app
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p historical-data logs

CMD ["python", "worker.py"]
