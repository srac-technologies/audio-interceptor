"""Per-meeting bot worker subprocess.

Spawned by the parent ``BotManager`` once per Meet session. Responsibilities:

  - Join the meeting via :class:`MeetAudioSource` (Phase 0 stealth recipe).
  - Run the chunking + transcription pipeline.
  - Emit one JSON object per line on **stdout** — the parent reads these and
    forwards them to the broker.
  - Log everything else to **stderr**, which the parent re-routes into its
    own logger.
  - Handle SIGTERM by closing the source (which leaves the Meet) and exiting
    cleanly so the BotManager's ``wait()`` returns promptly.

Stdout protocol (one JSON object per line, UTF-8, ``flush=True`` each line):

    {"type":"status","state":"joining|joined|left|error","detail":"..."}
    {"type":"transcript","source":"meet","speaker":"...","text":"...","ts":"...",
     "language":"ja","duration_s":7.4}

Anything other than these two types should be ignored by the parent.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import signal
import sys
from typing import Any

from .audio_pipeline import AudioPipeline
from .meet_audio_source import (
    MeetAdmissionError,
    MeetAntiBotWallError,
    MeetAudioSource,
)
from .transcribers import Transcriber

logger = logging.getLogger("bot_server.worker")


def _emit(obj: dict[str, Any]) -> None:
    """Write one JSON line to stdout, flushing immediately.

    The parent reads stdout with ``readline()``, so we must flush every line.
    """
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


async def _run(args: argparse.Namespace) -> int:
    # Logging goes to stderr; parent reads stderr separately and pipes it
    # into its own logger.
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    source = MeetAudioSource(
        meet_url=args.meet_url,
        bot_name=args.display_name or "DELTA AI",
        profile_dir=args.profile_dir,
        chrome_channel=args.chrome_channel,
        headless=args.headless,
        admission_timeout=args.admission_timeout,
    )

    # Set up SIGTERM handler so the BotManager can stop us cleanly.
    stop_event = asyncio.Event()

    def _on_signal(signum: int) -> None:
        logger.info("worker received signal %d, beginning shutdown", signum)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _on_signal, int(sig))
        except NotImplementedError:
            # Windows: skip; bot_server targets Linux for now.
            pass

    try:
        try:
            await source.join()
        except MeetAntiBotWallError as exc:
            _emit({"type": "status", "state": "error", "detail": f"anti-bot wall: {exc}"})
            return 2
        except MeetAdmissionError as exc:
            _emit({"type": "status", "state": "error", "detail": str(exc)})
            return 3
    except Exception as exc:  # noqa: BLE001
        _emit({"type": "status", "state": "error", "detail": f"join_failed: {exc!r}"})
        logger.exception("source.join raised")
        return 4

    # Load Whisper (this can take 5-30s for `small`). Emit a status note so
    # operators don't think we're hanging.
    _emit({"type": "status", "state": "joined", "detail": "loading transcription model"})
    try:
        transcriber = Transcriber(
            model_size=args.whisper_model,
            language=args.whisper_language,
        )
    except Exception as exc:  # noqa: BLE001
        _emit({"type": "status", "state": "error", "detail": f"whisper_load: {exc!r}"})
        logger.exception("Transcriber init failed")
        await source.close()
        return 5
    _emit({"type": "status", "state": "joined", "detail": "transcribing"})

    pipeline = AudioPipeline(
        transcriber=transcriber,
        chunk_seconds=args.chunk_seconds,
        silence_rms_threshold=args.silence_rms_threshold,
    )

    # Split the source's event stream: the pipeline only wants pcm + speaker,
    # status events should also flow up to stdout so the parent knows when
    # we're truly listening.
    source_events_q: asyncio.Queue = asyncio.Queue(maxsize=512)
    async def fan_source_events() -> None:
        async for ev in source.events():
            if ev.kind == "status":
                _emit({
                    "type": "status",
                    "state": ev.state or "unknown",
                    "detail": ev.detail,
                })
            else:
                await source_events_q.put(ev)
        await source_events_q.put(None)

    async def pipeline_input():
        while True:
            ev = await source_events_q.get()
            if ev is None:
                return
            yield ev

    async def transcript_publisher() -> None:
        async for tr in pipeline.transcripts():
            _emit({
                "type": "transcript",
                "source": "meet",
                "speaker": tr.speaker,
                "text": tr.text,
                "ts": tr.ts,
                "language": tr.language,
                "duration_s": round(tr.duration_s, 2),
            })

    fan_task = asyncio.create_task(fan_source_events(), name="fan_source_events")
    pipeline_task = asyncio.create_task(
        pipeline.run(pipeline_input()), name="pipeline_run"
    )
    publisher_task = asyncio.create_task(
        transcript_publisher(), name="transcript_publisher"
    )

    try:
        await stop_event.wait()
    finally:
        logger.info("worker: closing source")
        await source.close()
        # source.close() pushes the sentinel into events(); fan_task drains.
        for t in (fan_task, pipeline_task, publisher_task):
            try:
                await asyncio.wait_for(t, timeout=10.0)
            except asyncio.TimeoutError:
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t

    _emit({"type": "status", "state": "left", "detail": "worker exited"})
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--meet-url", required=True)
    p.add_argument("--display-name", default=None)
    p.add_argument("--profile-dir", default=None,
                   help="Persistent Chrome profile dir (recommended).")
    p.add_argument("--chrome-channel", default="chrome")
    p.add_argument("--headless", action="store_true", default=False)
    p.add_argument("--admission-timeout", type=float, default=180.0)
    p.add_argument("--whisper-model", default="small")
    p.add_argument("--whisper-language", default="ja")
    p.add_argument("--chunk-seconds", type=float, default=10.0)
    p.add_argument("--silence-rms-threshold", type=int, default=200)
    p.add_argument("--log-level", default="INFO")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    try:
        rc = asyncio.run(_run(args))
    except KeyboardInterrupt:
        rc = 130
    sys.exit(rc)


if __name__ == "__main__":
    main()
