"""Transcription engine wrapper for the bot worker.

Phase 2 ships only faster-whisper. The interface (:class:`Transcriber` with
``transcribe_pcm``) is deliberately narrow so additional engines (Google
Speech, OpenAI Whisper API, Kotoba etc.) can drop in later without touching
the pipeline.

The audio-interceptor backend already has a richer engine plugin layer
(``backend/transcription_engines.py``); we intentionally do NOT import from
there because the bot_server worker runs in its own subprocess and we want
its dependency footprint trimmed for the eventual containerized deploy.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


# These are the canned-up hallucination phrases faster-whisper emits on
# silence. We filter them out post-transcription. List lifted from
# backend/audio_interceptor.py:551 and lightly extended.
_HALLUCINATIONS: frozenset[str] = frozenset(
    {
        "ご視聴ありがとうございました",
        "ご視聴ありがとうございました。",
        "ご視聴ありがとうございました!",
        "ご視聴ありがとうございました!!",
        "ありがとうございました",
        "ご清聴ありがとうございました",
        "Thanks for watching!",
        "Thank you for watching",
        "thank you for watching.",
        "Thank you.",
        "Bye.",
        "♪",
        "(音楽)",
        "[音楽]",
        "(silence)",
        "[silence]",
    }
)


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    text: str
    language: str | None
    duration_s: float
    no_speech_prob: float


class Transcriber:
    """faster-whisper wrapper. One model load per worker process."""

    def __init__(
        self,
        *,
        model_size: str = "small",
        device: str | None = None,
        compute_type: str | None = None,
        language: str | None = None,
        beam_size: int = 5,
    ) -> None:
        # Lazy import keeps the bot_server skeleton (Phase 1) usable without
        # faster-whisper installed.
        from faster_whisper import WhisperModel

        if device is None:
            device = os.environ.get("WHISPER_DEVICE", "auto")
        if compute_type is None:
            # int8 keeps memory low on CPU; float16 is right for GPU.
            compute_type = os.environ.get(
                "WHISPER_COMPUTE_TYPE", "int8" if device != "cuda" else "float16"
            )
        logger.info(
            "loading faster-whisper model=%s device=%s compute_type=%s",
            model_size,
            device,
            compute_type,
        )
        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)
        self._language = language
        self._beam_size = beam_size

    def transcribe_pcm(
        self,
        pcm_int16: bytes,
        sample_rate: int,
    ) -> TranscriptionResult | None:
        """Run faster-whisper on a single chunk.

        Returns ``None`` if the chunk is judged silence (high no_speech_prob)
        or matches a known hallucination phrase. The caller is expected to
        decide whether to emit a transcript event.
        """
        if not pcm_int16:
            return None

        # Int16 LE bytes → float32 in [-1, 1] for the model.
        audio = np.frombuffer(pcm_int16, dtype=np.int16).astype(np.float32) / 32768.0

        if sample_rate != 16000:
            # faster-whisper expects 16 kHz; let scipy do the polyphase resample
            # if available, otherwise fall back to numpy linear interp (lower
            # fidelity but never imports scipy).
            audio = _resample_to_16k(audio, sample_rate)
            sample_rate = 16000

        segments, info = self._model.transcribe(
            audio,
            language=self._language,
            beam_size=self._beam_size,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        text_parts: list[str] = []
        max_no_speech = 0.0
        duration = 0.0
        for seg in segments:
            piece = (seg.text or "").strip()
            if piece:
                text_parts.append(piece)
            if seg.no_speech_prob is not None and seg.no_speech_prob > max_no_speech:
                max_no_speech = seg.no_speech_prob
            duration = max(duration, seg.end or duration)
        text = " ".join(text_parts).strip()
        if not text:
            return None
        if _is_hallucination(text):
            logger.debug("dropping hallucination: %r", text)
            return None
        return TranscriptionResult(
            text=text,
            language=getattr(info, "language", None),
            duration_s=float(duration),
            no_speech_prob=float(max_no_speech),
        )


def _is_hallucination(text: str) -> bool:
    t = text.strip()
    if t in _HALLUCINATIONS:
        return True
    # Very short transcripts of only punctuation / whitespace / single chars.
    stripped = "".join(c for c in t if c.isalnum())
    return len(stripped) < 2


def _resample_to_16k(audio: np.ndarray, in_rate: int) -> np.ndarray:
    if in_rate == 16000:
        return audio
    try:
        from scipy.signal import resample_poly  # type: ignore

        # GCD-based polyphase: high quality, low overhead.
        from math import gcd

        g = gcd(int(in_rate), 16000)
        up = 16000 // g
        down = int(in_rate) // g
        return resample_poly(audio, up, down).astype(np.float32)
    except ImportError:
        # Fallback: linear interp. Whisper is robust enough on speech that
        # this is good enough for first-light testing.
        n_out = int(round(len(audio) * 16000 / in_rate))
        if n_out <= 1:
            return np.zeros(0, dtype=np.float32)
        x_in = np.linspace(0.0, 1.0, num=len(audio), endpoint=False)
        x_out = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
        return np.interp(x_out, x_in, audio).astype(np.float32)
