"""Worker: pulls job ids from Redis, transcribes the audio, stores the result.

Run with: python -m app.worker
"""

import logging
import os
import pathlib
import signal
import tempfile
import time

from redis import Redis
from redis.exceptions import RedisError

from .config import load_settings
from .jobs import JobStore
from .transcriber import Transcriber, build_transcriber

log = logging.getLogger("worker")


def process(store: JobStore, transcriber: Transcriber, job_id: str) -> None:
    job = store.get(job_id)
    audio = store.audio(job_id)
    if job is None or audio is None:
        log.warning("job %s expired before processing", job_id)
        if job is not None:
            store.fail(job_id, "audio expired before processing")
        return

    store.mark_processing(job_id)
    started = time.monotonic()
    try:
        with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as f:
            f.write(audio)
            path = f.name
        try:
            result = transcriber.transcribe(path, job["language"] or None)
        finally:
            os.unlink(path)
    except Exception as exc:  # any decoding/model error marks the job failed, worker keeps running
        log.exception("job %s failed", job_id)
        store.fail(job_id, str(exc))
        return

    store.complete(job_id, result)
    log.info("job %s done in %.1fs (%.1fs of audio)", job_id, time.monotonic() - started, result.duration)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = load_settings()
    store = JobStore(Redis.from_url(settings.redis_url), settings.job_ttl_seconds)

    log.info("loading transcriber=%s model=%s", settings.transcriber, settings.whisper_model)
    transcriber = build_transcriber(settings)
    log.info("ready, waiting for jobs")

    running = True

    def stop(signum, _frame):
        nonlocal running
        log.info("signal %s received, finishing current job and exiting", signum)
        running = False

    # Kubernetes sends SIGTERM on pod shutdown; finish the current job instead of dying mid-way.
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    heartbeat = pathlib.Path(settings.heartbeat_file)
    while running:
        heartbeat.touch()
        try:
            job_id = store.next_job(timeout=5)
        except RedisError:
            log.warning("redis unavailable, retrying in 2s")
            time.sleep(2)
            continue
        if job_id:
            process(store, transcriber, job_id)


if __name__ == "__main__":
    main()
