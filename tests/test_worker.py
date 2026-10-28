import fakeredis

from app.jobs import JobStore
from app.transcriber import FakeTranscriber
from app.worker import process


class BrokenTranscriber:
    def transcribe(self, path, language=None):
        raise RuntimeError("could not decode audio")


def make_store():
    return JobStore(fakeredis.FakeRedis(), ttl_seconds=60)


def test_process_completes_job_and_deletes_audio():
    store = make_store()
    job_id = store.create(b"audio", "call.wav", "es")
    assert store.next_job(timeout=1) == job_id

    process(store, FakeTranscriber(), job_id)

    job = store.get(job_id)
    assert job["status"] == "done"
    assert job["text"] == "fake transcript"
    assert job["segments"] == []
    assert store.audio(job_id) is None


def test_process_marks_failure_and_keeps_running():
    store = make_store()
    job_id = store.create(b"audio", "call.wav", None)

    process(store, BrokenTranscriber(), job_id)

    job = store.get(job_id)
    assert job["status"] == "failed"
    assert "could not decode" in job["error"]
    assert store.audio(job_id) is None


def test_process_handles_expired_audio():
    store = make_store()
    job_id = store.create(b"audio", "call.wav", None)
    store.redis.delete(f"transcriber:audio:{job_id}")

    process(store, FakeTranscriber(), job_id)

    assert store.get(job_id)["status"] == "failed"
