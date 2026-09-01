from __future__ import annotations

import os

from temporalio.client import Client

TASK_QUEUE = "nepse-scraper-queue"
BACKFILL_WORKFLOW_NAME = "HistoricalBackfillWorkflow"

_client: Client | None = None


async def get_temporal_client() -> Client:
    """Lazily connects to the Temporal server, reusing the connection afterwards."""
    global _client
    if _client is None:
        address = os.getenv("TEMPORAL_ADDRESS", "temporal:7233")
        _client = await Client.connect(address)
    return _client
