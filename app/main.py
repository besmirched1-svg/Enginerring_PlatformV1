# app/main.py
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging

from app.api.routes import router
from app.utilities.logging import configure_logging

# Configure global logging
configure_logging()

# FastAPI application instance
web_app = FastAPI(
    title="OpenSCAD Engineering Platform",
    version="1.0.0"
)

# CORS (safe defaults)
web_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes
web_app.include_router(router)

logger = logging.getLogger("app.main")

@web_app.get("/health")
async def health():
    return {"status": "ok"}

@web_app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )
