"""FastAPI 应用入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from rag_core.api.logging_config import configure_rag_logging
from rag_core.api.routes.chat import router as chat_router
from rag_core.api.routes.ingest import router as ingest_router
from rag_core.api.routes.sessions import router as sessions_router
from rag_core.core.config import get_settings

configure_rag_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.redis = redis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield
    finally:
        await app.state.redis.aclose()


app = FastAPI(title="JuYao RAG API", version="0.1.0", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions_router)
app.include_router(chat_router)
app.include_router(ingest_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


def run() -> None:
    import uvicorn

    configure_rag_logging()
    s = get_settings()
    uvicorn.run("rag_core.api.app:app", host=s.rag_api_host, port=s.rag_api_port, log_level="info")


if __name__ == "__main__":
    run()
