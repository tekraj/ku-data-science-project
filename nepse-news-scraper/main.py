from __future__ import annotations
import os
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from config import load_app_config
from db import ensure_table_exists, get_connection

app = FastAPI(title="NEPSE News Pipeline API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_scheduler_thread: threading.Thread | None = None
_scheduler_lock = threading.Lock()
_historical_thread: threading.Thread | None = None
_historical_lock = threading.Lock()
_historical_status: dict[str, Any] = {
    "running": False,
    "status": "idle",
    "start_date": None,
    "end_date": None,
    "started_at": None,
    "finished_at": None,
    "summary": None,
    "error": None,
}

_AUTH_EMAIL = os.getenv("USER_EMAIL", "admin@ku.edu.np")
_AUTH_PASSWORD = os.getenv("USER_PASSWORD", "")
_JWT_SECRET = os.getenv("JWT_SECRET", "dev-only-nepse-jwt-secret-change-me")
_JWT_ALGO = "HS256"
_JWT_COOKIE_NAME = "nepse_access_token"
_JWT_TTL_MINUTES = int(os.getenv("JWT_TTL_MINUTES", "480"))
_COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"


class SignInRequest(BaseModel):
    email: str
    password: str


def _create_jwt(email: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=_JWT_TTL_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGO)


def _decode_jwt(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGO])
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from e


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_JWT_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="lax",
        max_age=_JWT_TTL_MINUTES * 60,
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(key=_JWT_COOKIE_NAME, path="/")


def _start_scheduler_once() -> None:
    global _scheduler_thread
    with _scheduler_lock:
        if _scheduler_thread is not None and _scheduler_thread.is_alive():
            return

        from scraper.scheduler import start_scheduler
        config = load_app_config()

        def _run():
            try:
                start_scheduler(config.scraper.interval_minutes, config.scraper)
            except Exception as e:
                print(f"[Scheduler] Crashed: {e}")

        _scheduler_thread = threading.Thread(target=_run, name="news-scheduler", daemon=True)
        _scheduler_thread.start()


def _parse_iso_date(value: str, field_name: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {field_name}; expected YYYY-MM-DD",
        ) from e


def _start_historical_backfill(start_date: date, end_date: date) -> bool:
    global _historical_thread

    with _historical_lock:
        if _historical_thread is not None and _historical_thread.is_alive():
            return False

        _historical_status.update(
            {
                "running": True,
                "status": "running",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": None,
                "summary": None,
                "error": None,
            }
        )

        # def _run() -> None:
        #     from scraper.scheduler import run_historical_backfill

        #     try:
        #         summary = run_historical_backfill(start_date=start_date, end_date=end_date)
        #         _historical_status.update(
        #             {
        #                 "running": False,
        #                 "status": "success",
        #                 "summary": summary,
        #                 "error": None,
        #                 "finished_at": datetime.now(timezone.utc).isoformat(),
        #             }
        #         )
        #     except Exception as e:
        #         _historical_status.update(
        #             {
        #                 "running": False,
        #                 "status": "failed",
        #                 "summary": None,
        #                 "error": str(e),
        #                 "finished_at": datetime.now(timezone.utc).isoformat(),
        #             }
        #         )

        # _historical_thread = threading.Thread(
        #     target=_run,
        #     name="historical-backfill",
        #     daemon=True,
        # )
        # _historical_thread.start()
        return True


@app.on_event("startup")
def on_startup() -> None:
    config = load_app_config()
    ensure_table_exists(config.database)
    _start_scheduler_once()


def _to_iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if isinstance(dt, datetime) else None


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]


def _require_auth(
    authorization: str | None = Header(default=None),
    access_cookie: str | None = Cookie(default=None, alias=_JWT_COOKIE_NAME),
) -> dict[str, Any]:
    token = _extract_bearer_token(authorization) or access_cookie
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization")
    return _decode_jwt(token)


def _fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    config = load_app_config()
    try:
        conn = get_connection(config.database)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}") from e

    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def _fetch_one(sql: str, params: tuple[Any, ...] = ()) -> tuple[Any, ...] | None:
    config = load_app_config()
    try:
        conn = get_connection(config.database)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}") from e

    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    finally:
        conn.close()


@app.post("/auth/signin")
def auth_signin(payload: SignInRequest, response: Response) -> dict[str, Any]:
    email = (payload.email or "").strip().lower()
    password = payload.password or ""

    if email != _AUTH_EMAIL or password != _AUTH_PASSWORD:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    token = _create_jwt(_AUTH_EMAIL)
    _set_auth_cookie(response, token)

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "email": _AUTH_EMAIL,
            "display_name": "Admin",
        },
    }


@app.post("/auth/logout")
def auth_logout(response: Response) -> dict[str, str]:
    _clear_auth_cookie(response)
    return {"message": "Signed out"}


@app.get("/auth/me")
def auth_me(claims: dict[str, Any] = Depends(_require_auth)) -> dict[str, Any]:
    return {
        "authenticated": True,
        "user": {
            "email": claims.get("sub", _AUTH_EMAIL),
            "display_name": "Admin",
        },
    }


# ── GET /articles ─────────────────────────────────────────────────────────

@app.get("/articles")
def get_articles(
    hours: int = Query(default=24, ge=1, le=720),
    tier: str = Query(default="all", description="all / finance / general"),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    """Returns recently scraped news articles."""
    params: list[Any] = [f"{hours} hours"]
    tier_filter = ""
    if tier in ("finance", "general"):
        tier_filter = "AND portal_tier = %s"
        params.append(tier)

    sql = f"""
        SELECT source, portal_tier, title, category, url, scraped_at
        FROM nepse_news
        WHERE scraped_at >= NOW() - %s::interval
          {tier_filter}
        ORDER BY scraped_at DESC
        LIMIT %s
    """
    params.append(limit)
    rows = _fetch_all(sql, tuple(params))

    return {
        "window_hours": hours,
        "total": len(rows),
        "articles": [
            {
                "source": r[0],
                "portal_tier": r[1],
                "title": r[2],
                "category": r[3],
                "url": r[4],
                "scraped_at": _to_iso(r[5]),
            }
            for r in rows
        ],
    }


# ── GET /nepse-index ──────────────────────────────────────────────────────

@app.get("/nepse-index")
def get_nepse_index(
    hours: int = Query(default=24, ge=1, le=720),
) -> dict[str, Any]:
    """Returns NEPSE main index and sector indices for the last N hours."""
    sql = """
        SELECT index_name, value, change, percent_change, scraped_at
        FROM nepse_index
        WHERE scraped_at >= NOW() - %s::interval
        ORDER BY scraped_at DESC
    """
    rows = _fetch_all(sql, (f"{hours} hours",))

    # Separate NEPSE main from sectors
    main = [r for r in rows if r[0] == "NEPSE"]
    sectors = [r for r in rows if r[0] != "NEPSE"]

    def fmt(r):
        return {
            "index": r[0],
            "value": r[1],
            "change": r[2],
            "percent_change": r[3],
            "scraped_at": _to_iso(r[4]),
        }

    return {
        "window_hours": hours,
        "nepse_main": [fmt(r) for r in main],
        "sector_indices": [fmt(r) for r in sectors],
    }


# ── Dashboard APIs ────────────────────────────────────────────────────────

@app.get("/dashboard/overview")
def dashboard_overview(
    hours: int = Query(default=24, ge=1, le=720),
    _: None = Depends(_require_auth),
) -> dict[str, Any]:
    article_stats_sql = """
        SELECT
            COUNT(*) AS total_articles,
            COUNT(DISTINCT source) AS total_sources,
            COUNT(*) FILTER (WHERE portal_tier = 'finance') AS finance_count,
            COUNT(*) FILTER (WHERE portal_tier = 'general') AS general_count,
            MAX(scraped_at) AS last_scraped_at
        FROM nepse_news
        WHERE scraped_at >= NOW() - %s::interval
    """
    article_stats = _fetch_one(article_stats_sql, (f"{hours} hours",))

    latest_index_sql = """
        SELECT index_name, value, change, percent_change, scraped_at
        FROM nepse_index
        WHERE index_name = 'NEPSE'
        ORDER BY scraped_at DESC
        LIMIT 1
    """
    latest_index = _fetch_one(latest_index_sql)

    sector_snap_sql = """
        SELECT DISTINCT ON (index_name)
            index_name, value, change, percent_change, scraped_at
        FROM nepse_index
        WHERE index_name <> 'NEPSE'
          AND scraped_at >= NOW() - %s::interval
        ORDER BY index_name, scraped_at DESC
    """
    sector_rows = _fetch_all(sector_snap_sql, (f"{hours} hours",))

    top_sources_sql = """
        SELECT source, COUNT(*) AS item_count
        FROM nepse_news
        WHERE scraped_at >= NOW() - %s::interval
        GROUP BY source
        ORDER BY item_count DESC, source ASC
        LIMIT 8
    """
    top_sources = _fetch_all(top_sources_sql, (f"{hours} hours",))

    return {
        "window_hours": hours,
        "stats": {
            "total_articles": int(article_stats[0] or 0) if article_stats else 0,
            "total_sources": int(article_stats[1] or 0) if article_stats else 0,
            "finance_count": int(article_stats[2] or 0) if article_stats else 0,
            "general_count": int(article_stats[3] or 0) if article_stats else 0,
            "last_scraped_at": _to_iso(article_stats[4]) if article_stats else None,
        },
        "nepse": {
            "index": latest_index[0] if latest_index else "NEPSE",
            "value": latest_index[1] if latest_index else None,
            "change": latest_index[2] if latest_index else None,
            "percent_change": latest_index[3] if latest_index else None,
            "scraped_at": _to_iso(latest_index[4]) if latest_index else None,
        },
        "sector_snapshot": [
            {
                "index": r[0],
                "value": r[1],
                "change": r[2],
                "percent_change": r[3],
                "scraped_at": _to_iso(r[4]),
            }
            for r in sector_rows
        ],
        "top_sources": [
            {"source": r[0], "item_count": int(r[1] or 0)} for r in top_sources
        ],
    }


@app.get("/dashboard/latest-news")
def dashboard_latest_news(
    limit: int = Query(default=15, ge=1, le=100),
    tier: str = Query(default="all", description="all / finance / general"),
    _: None = Depends(_require_auth),
) -> dict[str, Any]:
    params: list[Any] = []
    tier_filter = ""
    if tier in ("finance", "general"):
        tier_filter = "WHERE portal_tier = %s"
        params.append(tier)

    sql = f"""
        SELECT source, portal_tier, title, body, category, url, scraped_at
        FROM nepse_news
        {tier_filter}
        ORDER BY scraped_at DESC
        LIMIT %s
    """
    params.append(limit)
    rows = _fetch_all(sql, tuple(params))

    return {
        "total": len(rows),
        "news": [
            {
                "source": r[0],
                "portal_tier": r[1],
                "title": r[2],
                "body": r[3],
                "category": r[4],
                "url": r[5],
                "scraped_at": _to_iso(r[6]),
            }
            for r in rows
        ],
    }


@app.get("/dashboard/nepse-history")
def dashboard_nepse_history(
    hours: int = Query(default=24, ge=1, le=720),
    _: None = Depends(_require_auth),
) -> dict[str, Any]:
    sql = """
        SELECT index_name, value, change, percent_change, scraped_at
        FROM nepse_index
        WHERE index_name = 'NEPSE'
          AND scraped_at >= NOW() - %s::interval
        ORDER BY scraped_at ASC
    """
    rows = _fetch_all(sql, (f"{hours} hours",))

    return {
        "window_hours": hours,
        "points": [
            {
                "index": r[0],
                "value": r[1],
                "change": r[2],
                "percent_change": r[3],
                "scraped_at": _to_iso(r[4]),
            }
            for r in rows
        ],
    }


@app.get("/dashboard/sector-history")
def dashboard_sector_history(
    hours: int = Query(default=24, ge=1, le=720),
    _: None = Depends(_require_auth),
) -> dict[str, Any]:
    sql = """
        SELECT index_name, value, change, percent_change, scraped_at
        FROM nepse_index
        WHERE index_name <> 'NEPSE'
          AND scraped_at >= NOW() - %s::interval
        ORDER BY index_name ASC, scraped_at ASC
    """
    rows = _fetch_all(sql, (f"{hours} hours",))

    by_index: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        idx = r[0]
        by_index.setdefault(idx, []).append(
            {
                "index": r[0],
                "value": r[1],
                "change": r[2],
                "percent_change": r[3],
                "scraped_at": _to_iso(r[4]),
            }
        )

    return {
        "window_hours": hours,
        "series": by_index,
    }


@app.get("/dashboard/news")
def dashboard_news(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=5, le=100),
    tier: str = Query(default="all", description="all / finance / general"),
    source: str = Query(default="", description="Filter by source name (partial match)"),
    category: str = Query(default="", description="Filter by category (partial match)"),
    search: str = Query(default="", description="Search in title"),
    _: None = Depends(_require_auth),
) -> dict[str, Any]:
    """Paginated protected news listing, ordered by date desc."""
    conditions: list[str] = []
    params: list[Any] = []

    if tier in ("finance", "general"):
        conditions.append("portal_tier = %s")
        params.append(tier)
    if source.strip():
        conditions.append("LOWER(source) LIKE %s")
        params.append(f"%{source.strip().lower()}%")
    if category.strip():
        conditions.append("LOWER(category) LIKE %s")
        params.append(f"%{category.strip().lower()}%")
    if search.strip():
        conditions.append("LOWER(title) LIKE %s")
        params.append(f"%{search.strip().lower()}%")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    count_sql = f"SELECT COUNT(*) FROM nepse_news {where}"
    total_row = _fetch_one(count_sql, tuple(params))
    total = int(total_row[0] or 0) if total_row else 0
    total_pages = max(1, (total + page_size - 1) // page_size)
    offset = (page - 1) * page_size

    data_sql = f"""
        SELECT source, portal_tier, title, body, category, url, scraped_at
        FROM nepse_news
        {where}
        ORDER BY scraped_at DESC
        LIMIT %s OFFSET %s
    """
    rows = _fetch_all(data_sql, tuple(params) + (page_size, offset))

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "news": [
            {
                "source": r[0],
                "portal_tier": r[1],
                "title": r[2],
                "body": r[3],
                "category": r[4],
                "url": r[5],
                "scraped_at": _to_iso(r[6]),
            }
            for r in rows
        ],
    }


@app.get("/dashboard/pipeline-logs")
def dashboard_pipeline_logs(
    limit: int = Query(default=100, ge=1, le=1000),
    _: None = Depends(_require_auth),
) -> dict[str, Any]:
    sql = """
        SELECT
            id,
            status,
            message,
            error_text,
            news_total,
            news_inserted,
            nepse_records,
            nepse_source,
            started_at,
            finished_at,
            duration_ms,
            created_at
        FROM pipeline_run_logs
        ORDER BY started_at DESC NULLS LAST, id DESC
        LIMIT %s
    """
    rows = _fetch_all(sql, (limit,))

    logs = [
        {
            "id": r[0],
            "status": r[1],
            "message": r[2],
            "error_text": r[3],
            "news_total": int(r[4] or 0),
            "news_inserted": int(r[5] or 0),
            "nepse_records": int(r[6] or 0),
            "nepse_source": r[7],
            "started_at": _to_iso(r[8]),
            "finished_at": _to_iso(r[9]),
            "duration_ms": int(r[10] or 0),
            "created_at": _to_iso(r[11]),
        }
        for r in rows
    ]

    success = sum(1 for item in logs if item["status"] == "success")
    failed = sum(1 for item in logs if item["status"] != "success")

    return {
        "total": len(logs),
        "summary": {
            "success": success,
            "failed": failed,
            "last_run_at": logs[0]["started_at"] if logs else None,
        },
        "logs": logs,
    }


@app.post("/admin/historical/backfill")
def admin_start_historical_backfill(
    start_date: str = Query(default="2020-01-01", description="YYYY-MM-DD"),
    end_date: str = Query(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"), description="YYYY-MM-DD"),
    _: None = Depends(_require_auth),
) -> dict[str, Any]:
    start = _parse_iso_date(start_date, "start_date")
    end = _parse_iso_date(end_date, "end_date")

    # if end < start:
    #     raise HTTPException(
    #         status_code=status.HTTP_400_BAD_REQUEST,
    #         detail="end_date must be on or after start_date",
    #     )

    # launched = _start_historical_backfill(start, end)
    # if not launched:
    #     raise HTTPException(
    #         status_code=status.HTTP_409_CONFLICT,
    #         detail="Historical backfill is already running",
    #     )

    return {
        "message": "Historical backfill started",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }


@app.get("/admin/historical/backfill/status")
def admin_historical_backfill_status(_: None = Depends(_require_auth)) -> dict[str, Any]:
    return dict(_historical_status)


# ── GET /health ───────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8001")), reload=False)
