"""Audio chunking + transcription pipeline.

Sits between :class:`MeetAudioSource` (yields raw PCM events) and the bot
worker's stdout publisher. Responsibilities:

  - Accumulate Int16 PCM into ~chunk_seconds windows.
  - Drop silent chunks (avg amplitude below a threshold) to save Whisper CPU.
  - Run :class:`Transcriber` on each non-silent chunk in a thread (Whisper
    is CPU-bound and blocks; we keep the asyncio loop responsive).
  - Track the most-recently-seen active speaker name and attach it to
    transcript events.
  - Yield :class:`TranscriptEvent` dicts ready to JSON-serialize.

The pipeline never owns the source — the worker wires them together. This
makes unit testing easy: feed PCM events from a WAV file, observe transcripts.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .meet_audio_source import AudioEvent
from .transcribers import Transcriber, TranscriptionResult

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TranscriptEvent:
    text: str
    speaker: str | None
    ts: str
    language: str | None
    duration_s: float


@dataclass(slots=True)
class _Buffer:
    sample_rate: int = 0
    bytes_per_sample: int = 2  # Int16
    chunk_seconds: float = 10.0
    silence_rms_threshold: int = 200  # Int16-scale; ~0.6% of full scale.
    pcm: bytearray = field(default_factory=bytearray)

    @property
    def target_bytes(self) -> int:
        return int(self.chunk_seconds * self.sample_rate) * self.bytes_per_sample

    def add(self, data: bytes) -> None:
        self.pcm.extend(data)

    def ready(self) -> bool:
        return self.sample_rate > 0 and len(self.pcm) >= self.target_bytes

    def take_chunk(self) -> bytes:
        size = self.target_bytes
        chunk = bytes(self.pcm[:size])
        del self.pcm[:size]
        return chunk

    def is_silence(self, chunk: bytes) -> bool:
        """Crude RMS-on-Int16 check. Cheap; runs synchronously."""
        if not chunk:
            return True
        # numpy is already a dep via transcribers. Inline-import keeps the
        # module load fast for callers that don't need it.
        import numpy as np

        samples = np.frombuffer(chunk, dtype=np.int16)
        if samples.size == 0:
            return True
        rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
        return rms < float(self.silence_rms_threshold)


class AudioPipeline:
    """Glue between a :class:`MeetAudioSource` and the transcript stream."""

    def __init__(
        self,
        *,
        transcriber: Transcriber,
        chunk_seconds: float = 10.0,
        silence_rms_threshold: int = 200,
        executor: object | None = None,  # concurrent.futures.Executor | None
    ) -> None:
        self._transcriber = transcriber
        self._chunk_seconds = chunk_seconds
        self._silence_rms_threshold = silence_rms_threshold
        self._executor = executor
        self._buffer = _Buffer(
            chunk_seconds=chunk_seconds,
            silence_rms_threshold=silence_rms_threshold,
        )
        self._last_speaker: str | None = None
        # Output queue (transcripts only). Status / speaker events are
        # observable via :meth:`status_events` and :meth:`speaker_events`
        # if the worker wants to forward them too.
        self._out: asyncio.Queue[TranscriptEvent | None] = asyncio.Queue(maxsize=64)

    async def run(self, source_events: AsyncIterator[AudioEvent]) -> None:
        """Consume the source's events until exhausted, populating ``transcripts``.

        Forwards status events into the log only — the worker re-emits status
        from elsewhere (it knows about the subprocess lifecycle).
        """
        try:
            async for ev in source_events:
                if ev.kind == "pcm":
                    if ev.sample_rate and self._buffer.sample_rate == 0:
                        self._buffer.sample_rate = ev.sample_rate
                        logger.info(
                            "audio_pipeline: sample_rate=%d Hz target_bytes=%d (chunk %.1fs)",
                            ev.sample_rate,
                            self._buffer.target_bytes,
                            self._chunk_seconds,
                        )
                    if ev.data:
                        self._buffer.add(ev.data)
                    while self._buffer.ready():
                        await self._process_chunk()
                elif ev.kind == "speaker":
                    self._last_speaker = ev.speaker_name
                elif ev.kind == "status":
                    logger.debug("source status: %s (%s)", ev.state, ev.detail)
        finally:
            await self._out.put(None)

    def transcripts(self) -> AsyncIterator[TranscriptEvent]:
        return self._transcript_iter()

    async def _transcript_iter(self) -> AsyncIterator[TranscriptEvent]:
        while True:
            ev = await self._out.get()
            if ev is None:
                return
            yield ev

    async def _process_chunk(self) -> None:
        chunk = self._buffer.take_chunk()
        # Compute RMS once so we can log it regardless of the silence verdict.
        import numpy as np
        samples = np.frombuffer(chunk, dtype=np.int16)
        rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))) if samples.size else 0.0
        if rms < float(self._silence_rms_threshold):
            logger.info(
                "audio_pipeline: dropping silent chunk rms=%.1f (threshold=%d)",
                rms, self._silence_rms_threshold,
            )
            return
        logger.info("audio_pipeline: transcribing chunk rms=%.1f", rms)
        loop = asyncio.get_running_loop()
        sample_rate = self._buffer.sample_rate
        result: TranscriptionResult | None = await loop.run_in_executor(
            self._executor,
            self._transcriber.transcribe_pcm,
            chunk,
            sample_rate,
        )
        if result is None:
            return
        await self._out.put(
            TranscriptEvent(
                text=result.text,
                speaker=self._last_speaker,
                ts=datetime.now(timezone.utc).isoformat(),
                language=result.language,
                duration_s=result.duration_s,
            )
        )
