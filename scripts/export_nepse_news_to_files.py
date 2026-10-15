#!/usr/bin/env python3
"""Export `nepse_news` table `body` column to local files under data/nepse_news/{id}.txt

Usage:
    python scripts/export_nepse_news_to_files.py

Reads DB config from nepse-common config loader (env vars supported).
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

try:
    # prefer in-repo shared config if available
    from nepse_common.config import load_app_config
    HAVE_NEPCONFIG = True
except Exception:
    HAVE_NEPCONFIG = False

import psycopg2
from psycopg2.extras import RealDictCursor


def get_db_params_from_env():
    return {
        "host": os.getenv("POSTGRES_HOST", "db"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "dbname": os.getenv("POSTGRES_DB", "wikipedia"),
        "user": os.getenv("POSTGRES_USER", "superset"),
        "password": os.getenv("POSTGRES_PASSWORD", "superset_pass"),
    }


def main():
    base = Path("data/nepse_news")
    base.mkdir(parents=True, exist_ok=True)

    if HAVE_NEPCONFIG:
        cfg = load_app_config()
        db = {
            "host": cfg.database.host,
            "port": cfg.database.port,
            "dbname": cfg.database.dbname,
            "user": cfg.database.user,
            "password": cfg.database.password,
        }
    else:
        # Static defaults taken from docker-compose.yml for quick local runs.
        # Use localhost because `db` hostname is only resolvable inside docker
        # networks; the compose file maps container port 5432 to host 5432.
        db = {
            "host": "localhost",
            "port": 5432,
            "dbname": "nepse",
            "user": "superset",
            "password": "superset_pass",
        }

    conn = psycopg2.connect(**db)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    batch_size = 1000
    offset = 0
    while True:
        cur.execute(
            "SELECT id, body FROM nepse_news ORDER BY id LIMIT %s OFFSET %s",
            (batch_size, offset),
        )
        rows = cur.fetchall()
        if not rows:
            break

        for row in rows:
            _id = row.get("id")
            body = row.get("body") or ""
            dest = base / f"{_id}.txt"
            with dest.open("w", encoding="utf-8") as fh:
                fh.write(body)

        offset += len(rows)

    cur.close()
    conn.close()

    print(f"Wrote files to {base.resolve()}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("Error:", e, file=sys.stderr)
        sys.exit(1)
