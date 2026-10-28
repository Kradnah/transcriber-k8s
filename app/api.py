import secrets
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Path, UploadFile, status
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest
from redis import Redis
from redis.exceptions import RedisError

from .config import Settings, load_settings
from .jobs import JobStore

JOBS_CREATED = Counter("transcriber_jobs_created_total", "Transcription jobs accepted")
QUEUE_LENGTH = Gauge("transcriber_queue_length", "Jobs waiting for a worker")

JobId = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]

app = FastAPI(title="transcriber", version="0.1.0")


@lru_cache
def get_settings() -> Settings:
    return load_settings()


@lru_cache
def get_store() -> JobStore:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, socket_timeout=5, socket_connect_timeout=5)
    return JobStore(redis, settings.job_ttl_seconds)


def require_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    if not settings.api_key:
        return
    if x_api_key is None or not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing API key")


@app.get("/healthz")
def healthz() -> dict:
    """Liveness: the process is up. Does not touch Redis, so a Redis outage won't restart API pods."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz(store: Annotated[JobStore, Depends(get_store)]) -> dict:
    """Readiness: only receive traffic while Redis is reachable."""
    try:
        store.redis.ping()
    except RedisError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "redis unavailable")
    return {"status": "ready"}


@app.post(
    "/v1/transcriptions",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_api_key)],
)
async def create_transcription(
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[JobStore, Depends(get_store)],
    file: UploadFile = File(...),
    language: str | None = Form(default=None, max_length=8),
) -> dict:
    data = await file.read(settings.max_upload_bytes + 1)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty file")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"file larger than {settings.max_upload_mb} MB",
        )
    job_id = store.create(data, file.filename or "audio", language)
    JOBS_CREATED.inc()
    return {"id": job_id, "status": "queued"}


@app.get("/v1/transcriptions/{job_id}", dependencies=[Depends(require_api_key)])
def get_transcription(job_id: JobId, store: Annotated[JobStore, Depends(get_store)]) -> dict:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found or expired")
    return job


@app.get("/metrics")
def metrics(store: Annotated[JobStore, Depends(get_store)]) -> Response:
    try:
        QUEUE_LENGTH.set(store.queue_length())
    except RedisError:
        pass
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
