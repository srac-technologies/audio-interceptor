"""Fake worker for the bot_server stdout-protocol smoke test.

Mimics :mod:`bot_server.worker` enough to exercise the parent's stdout reader
+ broker fan-out without launching Playwright or faster-whisper. Switch the
parent over to this fake by setting ``WORKER_MODULE=bot_server._fake_worker``
in the environment.

Emits one status:joining → status:joined → status:transcribing → periodic
fake transcripts → status:left (on SIGTERM). Pure stdlib so it runs in any
venv that has Python.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
from datetime import datetime, timezone


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


async def main() -> int:
    parser = argparse.ArgumentParser()
    # Accept the same CLI surface as bot_server.worker so the parent's
    # command-builder doesn't care which module it ends up invoking.
    parser.add_argument("--meet-url", required=True)
    parser.add_argument("--display-name", default="FakeBot")
    parser.add_argument("--profile-dir", default=None)
    parser.add_argument("--chrome-channel", default="chrome")
    parser.add_argument("--headless", action="store_true", default=False)
    parser.add_argument("--admission-timeout", type=float, default=180.0)
    parser.add_argument("--whisper-model", default="small")
    parser.add_argument("--whisper-language", default="ja")
    parser.add_argument("--chunk-seconds", type=float, default=10.0)
    parser.add_argument("--silence-rms-threshold", type=int, default=200)
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--fake-interval", type=float, default=2.0)
    args = parser.parse_args()

    print(
        f"fake_worker: starting meet_url={args.meet_url} display_name={args.display_name}",
        file=sys.stderr,
        flush=True,
    )

    _emit({"type": "status", "state": "joining", "detail": "fake worker", "ts": _ts()})
    await asyncio.sleep(0.2)
    _emit({"type": "status", "state": "joined", "detail": "fake admitted", "ts": _ts()})

    stop = asyncio.Event()

    def _on_sig(_sig: int) -> None:
        print("fake_worker: signal received", file=sys.stderr, flush=True)
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _on_sig, int(sig))
        except NotImplementedError:
            pass

    phrases = [
        "これはフェイクワーカーが出している擬似 transcript です。",
        "BotSession の stdout reader と broker fan-out の疎通確認用。",
        "SIGTERM が来たら 'left' を出して終了します。",
    ]
    i = 0
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=args.fake_interval)
            break
        except asyncio.TimeoutError:
            pass
        _emit(
            {
                "type": "transcript",
                "source": "meet",
                "speaker": args.display_name,
                "text": phrases[i % len(phrases)],
                "ts": _ts(),
                "language": args.whisper_language,
                "duration_s": round(args.fake_interval, 2),
            }
        )
        i += 1

    _emit({"type": "status", "state": "left", "detail": "fake worker exit", "ts": _ts()})
    return 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(main())
    except KeyboardInterrupt:
        rc = 130
    sys.exit(rc)
