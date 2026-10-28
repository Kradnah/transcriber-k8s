from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .config import Settings


@dataclass
class Transcript:
    text: str
    language: str
    duration: float
    segments: list[dict] = field(default_factory=list)


class Transcriber(Protocol):
    def transcribe(self, path: str, language: str | None = None) -> Transcript: ...


class FakeTranscriber:
    """Returns a fixed transcript. Used in tests and CI, where downloading a model is wasteful."""

    def transcribe(self, path: str, language: str | None = None) -> Transcript:
        return Transcript(text="fake transcript", language=language or "es", duration=0.0)


class WhisperTranscriber:
    """CPU transcription with faster-whisper (CTranslate2). int8 keeps RAM low on a small VPS."""

    def __init__(self, model_name: str, compute_type: str, cache_dir: str):
        from faster_whisper import WhisperModel

        self.model = WhisperModel(
            model_name, device="cpu", compute_type=compute_type, download_root=cache_dir
        )

    def transcribe(self, path: str, language: str | None = None) -> Transcript:
        segments, info = self.model.transcribe(path, language=language, vad_filter=True)
        segs = [
            {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
            for s in segments
        ]
        return Transcript(
            text=" ".join(s["text"] for s in segs),
            language=info.language,
            duration=round(info.duration, 2),
            segments=segs,
        )


def build_transcriber(settings: "Settings") -> Transcriber:
    if settings.transcriber == "fake":
        return FakeTranscriber()
    return WhisperTranscriber(
        settings.whisper_model, settings.whisper_compute_type, settings.model_cache_dir
    )
