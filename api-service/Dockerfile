# Build context MUST be the repo root, e.g.:
#   docker build -f api-service/Dockerfile -t api-service .
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install the shared nepse-common package first so its layer is cached
# independently of api-service source changes.
COPY nepse-common /nepse-common
RUN pip install --no-cache-dir -e /nepse-common

COPY api-service /app
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
