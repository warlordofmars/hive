"""
Hive management FastAPI application.

Runs on port 8001 in development.
All /api/* routes require a valid OAuth 2.1 Bearer token.
OAuth endpoints (/oauth/*, /.well-known/*) are public.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hive.auth.oauth import router as oauth_router
from hive.api.memories import router as memories_router
from hive.api.clients import router as clients_router
from hive.api.stats import router as stats_router

app = FastAPI(
    title="Hive Management API",
    version="0.1.0",
    description="REST API for managing Hive memories, OAuth clients, and viewing activity stats.",
)

# Allow the React dev server (port 5173) and any configured UI origin
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OAuth 2.1 endpoints (unauthenticated)
app.include_router(oauth_router)

# Management API endpoints (Bearer token required)
app.include_router(memories_router, prefix="/api")
app.include_router(clients_router, prefix="/api")
app.include_router(stats_router, prefix="/api")


@app.get("/health", include_in_schema=False)
async def health() -> dict:
    return {"status": "ok"}


def lambda_handler(event: dict, context: object) -> dict:
    """AWS Lambda + Function URL handler for the management API."""
    try:
        from mangum import Mangum
    except ImportError as exc:
        raise RuntimeError("mangum is required for Lambda deployment") from exc

    handler = Mangum(app, lifespan="off")
    return handler(event, context)
