import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .db import create_tables, init_db_globals, _session_factory, get_session_factory, get_engine
from .models import user, job  # noqa: register models
from .routes import auth, users, jobs, sources, wiki
from .services.worker import init_worker, worker_loop
from .config import get_settings
from pathlib import Path

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    init_db_globals()
    await create_tables()

    Path(settings.source_store_path).mkdir(parents=True, exist_ok=True)
    Path(settings.wiki_store_path).mkdir(parents=True, exist_ok=True)

    from .db import _session_factory
    init_worker(_session_factory)

    worker_task = asyncio.create_task(worker_loop())

    yield

    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Sheska", version="0.1.0", lifespan=lifespan)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(jobs.router)
app.include_router(sources.router)
app.include_router(wiki.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
