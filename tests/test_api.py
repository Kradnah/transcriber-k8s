import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.api import app, get_settings, get_store
from app.config import Settings
from app.jobs import JobStore

API_KEY = "test-key"


@pytest.fixture
def store():
    return JobStore(fakeredis.FakeRedis(), ttl_seconds=60)


@pytest.fixture
def client(store):
    settings = Settings(
        redis_url="redis://unused",
        api_key=API_KEY,
        max_upload_mb=1,
        job_ttl_seconds=60,
        transcriber="fake",
        whisper_model="base",
        whisper_compute_type="int8",
        model_cache_dir="/tmp",
        heartbeat_file="/tmp/hb",
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_store] = lambda: store
    yield TestClient(app)
    app.dependency_overrides.clear()


def upload(client, content=b"RIFFfakeaudio", headers=None):
    return client.post(
        "/v1/transcriptions",
        files={"file": ("call.wav", content, "audio/wav")},
        data={"language": "es"},
        headers=headers if headers is not None else {"X-API-Key": API_KEY},
    )


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_readyz(client):
    assert client.get("/readyz").status_code == 200


def test_upload_requires_api_key(client):
    assert upload(client, headers={}).status_code == 401
    assert upload(client, headers={"X-API-Key": "wrong"}).status_code == 401


def test_upload_queues_job(client, store):
    resp = upload(client)
    assert resp.status_code == 202
    job_id = resp.json()["id"]
    assert store.queue_length() == 1

    job = client.get(f"/v1/transcriptions/{job_id}", headers={"X-API-Key": API_KEY}).json()
    assert job["status"] == "queued"
    assert job["language"] == "es"


def test_upload_rejects_empty_and_too_large(client):
    assert upload(client, content=b"").status_code == 400
    assert upload(client, content=b"x" * (1024 * 1024 + 1)).status_code == 413


def test_unknown_and_malformed_job_ids(client):
    headers = {"X-API-Key": API_KEY}
    assert client.get(f"/v1/transcriptions/{'0' * 32}", headers=headers).status_code == 404
    assert client.get("/v1/transcriptions/not-a-job", headers=headers).status_code == 422


def test_metrics_exposes_queue_length(client):
    upload(client)
    body = client.get("/metrics").text
    assert "transcriber_queue_length 1.0" in body
