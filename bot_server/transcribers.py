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
        "ありがとうございました。",
        "ありがとうございました!",
        "ご清聴ありがとうございました",
        "ご清聴ありがとうございました。",
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
    """Polymorphic wrapper: faster-whisper (default) or openai-whisper.

    Backend pick via ``WHISPER_BACKEND`` env (``faster-whisper`` /
    ``openai-whisper``). openai-whisper runs on PyTorch and works on
    ROCm-built torch — set ``WHISPER_DEVICE=cuda`` to use the AMD GPU.
    """

    def __init__(
        self,
        *,
        model_size: str = "small",
        device: str | None = None,
        compute_type: str | None = None,
        language: str | None = None,
        beam_size: int = 5,
        backend: str | None = None,
    ) -> None:
        if device is None:
            device = os.environ.get("WHISPER_DEVICE", "auto")
        if backend is None:
            backend = os.environ.get("WHISPER_BACKEND", "faster-whisper").strip()
        self._backend = backend
        self._language = language
        self._beam_size = beam_size

        if backend == "openai-whisper":
            import whisper  # PyTorch-backed; works with ROCm-built torch
            # 'auto' → cuda if available, else cpu.
            if device == "auto":
                try:
                    import torch
                    device = "cuda" if torch.cuda.is_available() else "cpu"
                except ImportError:
                    device = "cpu"
            logger.info(
                "loading openai-whisper model=%s device=%s",
                model_size, device,
            )
            self._fw_model = None
            self._ow_model = whisper.load_model(model_size, device=device)
            self._device = device
            return

        # default: faster-whisper
        from faster_whisper import WhisperModel
        if compute_type is None:
            compute_type = os.environ.get(
                "WHISPER_COMPUTE_TYPE", "int8" if device != "cuda" else "float16"
            )
        logger.info(
            "loading faster-whisper model=%s device=%s compute_type=%s",
            model_size, device, compute_type,
        )
        self._fw_model = WhisperModel(
            model_size, device=device, compute_type=compute_type
        )
        self._ow_model = None
        self._device = device

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
            audio = _resample_to_16k(audio, sample_rate)
            sample_rate = 16000

        if self._backend == "openai-whisper":
            # openai-whisper takes float32 numpy in [-1, 1] at 16 kHz.
            result = self._ow_model.transcribe(
                audio,
                language=self._language,
                fp16=(self._device == "cuda"),
                temperature=0.0,
                condition_on_previous_text=False,
                no_speech_threshold=0.6,
            )
            text = (result.get("text") or "").strip()
            if not text:
                return None
            logger.info(
                "whisper raw text: %r (lang=%s)",
                text, result.get("language"),
            )
            if _is_hallucination(text):
                logger.info("dropping hallucination: %r", text)
                return None
            return TranscriptionResult(
                text=text,
                language=result.get("language"),
                duration_s=float(len(audio)) / 16000.0,
                no_speech_prob=0.0,
            )

        # faster-whisper path
        segments, info = self._fw_model.transcribe(
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
        logger.info(
            "whisper raw text: %r (parts=%d max_no_speech=%.2f)",
            text, len(text_parts), max_no_speech,
        )
        if not text:
            return None
        # Whisper's own no_speech head — if the model itself says this
        # segment is probably not speech, trust it. Filters out the bulk
        # of "ありがとうございました" / "ご視聴..." hallucinations.
        if max_no_speech > 0.6:
            logger.info(
                "dropping by no_speech_prob=%.2f: %r", max_no_speech, text,
            )
            return None
        if _is_hallucination(text):
            logger.info("dropping hallucination: %r", text)
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
