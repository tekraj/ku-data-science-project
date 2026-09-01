from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import admin, articles, auth, dashboard, health

app = FastAPI(title="NEPSE News Pipeline API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(articles.router)
app.include_router(dashboard.router, prefix="/dashboard")
app.include_router(admin.router, prefix="/admin")
app.include_router(auth.router, prefix="/auth")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8001")), reload=False)
