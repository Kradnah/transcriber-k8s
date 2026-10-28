import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    redis_url: str
    api_key: str
    max_upload_mb: int
    job_ttl_seconds: int
    transcriber: str
    whisper_model: str
    whisper_compute_type: str
    model_cache_dir: str
    heartbeat_file: str

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


def load_settings() -> Settings:
    env = os.environ.get
    return Settings(
        redis_url=env("REDIS_URL", "redis://localhost:6379/0"),
        # Empty API_KEY disables auth (local development only). Strip so a key created
        # from a file (trailing newline) still matches the header value.
        api_key=env("API_KEY", "").strip(),
        max_upload_mb=int(env("MAX_UPLOAD_MB", "10")),
        job_ttl_seconds=int(env("JOB_TTL_SECONDS", "86400")),
        # "whisper" for real transcription, "fake" for tests and CI.
        transcriber=env("TRANSCRIBER", "whisper"),
        whisper_model=env("WHISPER_MODEL", "base"),
        whisper_compute_type=env("WHISPER_COMPUTE_TYPE", "int8"),
        model_cache_dir=env("MODEL_CACHE_DIR", "/models"),
        heartbeat_file=env("HEARTBEAT_FILE", "/tmp/worker-heartbeat"),
    )
