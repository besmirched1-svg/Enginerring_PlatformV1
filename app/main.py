# app/main.py

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.api.websocket import (
    router as ws_router,
    start_bridge,
    stop_bridge,
)
from app.utilities.logging import configure_logging

configure_logging()
logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the Redis -> websocket bridge before any client can connect.
    await start_bridge()
    try:
        yield
    finally:
        await stop_bridge()


web_app = FastAPI(
    title="OpenSCAD Engineering Platform",
    version="1.0.0",
    lifespan=lifespan,
)

web_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

web_app.include_router(router)
web_app.include_router(ws_router)


@web_app.get("/health")
async def health():
    return {"status": "ok"}


@web_app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
