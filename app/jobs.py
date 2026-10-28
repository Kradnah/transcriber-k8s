"""Job queue and state, stored in Redis.

Keys:
  transcriber:queue          list of pending job ids
  transcriber:job:<id>       hash with status and result
  transcriber:audio:<id>     raw uploaded audio (deleted once processed)
"""

import json
import time
import uuid

from redis import Redis

from .transcriber import Transcript

QUEUE_KEY = "transcriber:queue"


def _job_key(job_id: str) -> str:
    return f"transcriber:job:{job_id}"


def _audio_key(job_id: str) -> str:
    return f"transcriber:audio:{job_id}"


class JobStore:
    def __init__(self, redis: Redis, ttl_seconds: int):
        self.redis = redis
        self.ttl = ttl_seconds

    def create(self, audio: bytes, filename: str, language: str | None) -> str:
        job_id = uuid.uuid4().hex
        pipe = self.redis.pipeline()
        pipe.set(_audio_key(job_id), audio, ex=self.ttl)
        pipe.hset(
            _job_key(job_id),
            mapping={
                "status": "queued",
                "filename": filename,
                "language": language or "",
                "created_at": time.time(),
            },
        )
        pipe.expire(_job_key(job_id), self.ttl)
        pipe.rpush(QUEUE_KEY, job_id)
        pipe.execute()
        return job_id

    def get(self, job_id: str) -> dict | None:
        data = self.redis.hgetall(_job_key(job_id))
        if not data:
            return None
        job = {k.decode(): v.decode() for k, v in data.items()}
        job["id"] = job_id
        if "segments" in job:
            job["segments"] = json.loads(job["segments"])
        return job

    def next_job(self, timeout: int = 5) -> str | None:
        item = self.redis.blpop([QUEUE_KEY], timeout=timeout)
        return item[1].decode() if item else None

    def audio(self, job_id: str) -> bytes | None:
        return self.redis.get(_audio_key(job_id))

    def mark_processing(self, job_id: str) -> None:
        self.redis.hset(_job_key(job_id), "status", "processing")

    def complete(self, job_id: str, result: Transcript) -> None:
        pipe = self.redis.pipeline()
        pipe.hset(
            _job_key(job_id),
            mapping={
                "status": "done",
                "text": result.text,
                "language": result.language,
                "duration": result.duration,
                "segments": json.dumps(result.segments),
                "finished_at": time.time(),
            },
        )
        pipe.delete(_audio_key(job_id))
        pipe.execute()

    def fail(self, job_id: str, error: str) -> None:
        pipe = self.redis.pipeline()
        pipe.hset(_job_key(job_id), mapping={"status": "failed", "error": error[:500]})
        pipe.delete(_audio_key(job_id))
        pipe.execute()

    def queue_length(self) -> int:
        return self.redis.llen(QUEUE_KEY)
