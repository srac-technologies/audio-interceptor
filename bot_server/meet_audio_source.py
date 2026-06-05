"""Playwright-driven Google Meet audio source.

Joins a Meet URL with the stealth-tweaked plain Playwright recipe validated
in Phase 0 (see ``feedback-meet-bot-stealth`` memory), installs the in-page
audio bridge (``bootstrap_audio.js``) only after admission, and yields
Int16 PCM chunks + active-speaker updates as async events.

Public surface:
    src = MeetAudioSource(meet_url=..., profile_dir=..., bot_name=...)
    await src.join()
    async for event in src.events():
        if event.kind == "pcm":
            # event.data is bytes (Int16 LE), event.sample_rate is Hz
        elif event.kind == "speaker":
            # event.speaker_name is str | None
        elif event.kind == "status":
            # event.state in {"joining","joined","left","error"}
    await src.close()

Each session owns its own Chromium subprocess (via Playwright). Concurrent
meetings = concurrent ``MeetAudioSource`` instances, each in its own process
(spawned by the bot_server worker subprocess pattern). One Chrome ↔ one Meet.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import os
import random
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)


_BOOTSTRAP_PATH = Path(__file__).resolve().parent / "bootstrap_audio.js"


@dataclass(frozen=True, slots=True)
class AudioEvent:
    """Wraps everything we publish from the in-page bridge.

    ``kind`` is one of:
      - "pcm": ``data`` is the raw Int16-LE bytes at ``sample_rate`` Hz.
      - "speaker": ``speaker_name`` is the active speaker (may be None /
        empty string when nobody is talking).
      - "status": ``state`` ∈ {"joining","joined","left","error"};
        ``detail`` is a short human-readable note.
    """

    kind: Literal["pcm", "speaker", "status"]
    data: bytes | None = None
    sample_rate: int | None = None
    speaker_name: str | None = None
    state: str | None = None
    detail: str | None = None


# ----- JS helpers (small enough to inline) -----------------------------------

_LOCATE_RECT_JS = r"""
(sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  if (r.width === 0 || r.height === 0) return null;
  return {
    x: r.left + r.width / 2,
    y: r.top + r.height / 2,
    w: r.width,
    h: r.height,
  };
}
"""

_LOCATE_BUTTON_BY_TEXT_JS = r"""
(labels) => {
  const lowered = labels.map(l => l.toLowerCase());
  const buttons = Array.from(document.querySelectorAll('button, [role="button"]'));
  for (const b of buttons) {
    const text = (b.textContent || '').toLowerCase().trim();
    const aria = (b.getAttribute('aria-label') || '').toLowerCase().trim();
    if (!text && !aria) continue;
    if (lowered.some(l => text.includes(l) || aria.includes(l))) {
      const r = b.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      return { x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height };
    }
  }
  return null;
}
"""

_ADMITTED_PROBE_JS = r"""
() => {
  const videos = Array.from(document.querySelectorAll('video'));
  if (videos.some(v => v.videoWidth > 0 && v.videoHeight > 0)) return true;
  const buttons = Array.from(document.querySelectorAll('button, [role="button"]'));
  for (const b of buttons) {
    const label = (b.getAttribute('aria-label') || '').toLowerCase();
    if (label.includes('leave call') || label.includes('通話を終了') || label.includes('退出')) {
      return true;
    }
  }
  return false;
}
"""

_WALL_TEXT_JS = (
    "() => (document.body && document.body.innerText || '').slice(0, 4000)"
)

# Stealth defaults — Phase 0 receipts.
#
# We DO add fake media-stream flags here (unlike posture-feedback, which is a
# camera-analysis app). Without `--use-fake-device-for-media-stream`, Chrome
# under xvfb has no microphone hardware and Meet renders a "Microphone not
# found" toast, then declines to establish the full WebRTC media path — no
# remote audio tracks ever arrive. With the fake device, Meet sees a normal
# (muted) mic and proceeds with the bidirectional session, so remote
# participants' audio flows in.
_DEFAULT_CHROME_ARGS = (
    "--autoplay-policy=no-user-gesture-required",
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--use-fake-device-for-media-stream",
    "--use-fake-ui-for-media-stream",
)
_DEFAULT_IGNORE_DEFAULT_ARGS = (
    "--enable-automation",
    "--enable-blink-features=IdleDetection",
)
_WEBDRIVER_OVERRIDE_JS = (
    "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
)

# Pre-navigation RTC capture. Minimal scope: just wrap the constructor so we
# observe every PC's "track" events and stash inbound MediaStreamTracks in
# ``window.__meetCapturedTracks`` for the main bridge (installed
# post-admission) to pipe into AudioContext. Meet 2026 renders participant
# audio through Web Audio directly, never via <audio>/<video> elements, so
# this is the only reliable hook for the audio path. Phase 0 spike showed
# Meet's anti-bot rejects pre-injection of the FULL bridge, but a tiny RTC
# wrap (no expose_function, no AudioWorklet, no expose globals beyond a
# single array) has a small enough footprint that we accept the risk.
_PRE_NAV_RTC_WRAP_JS = r"""
(() => {
  if (window.__meetRtcWrapped) return;
  window.__meetRtcWrapped = true;
  window.__meetCapturedTracks = window.__meetCapturedTracks || [];
  try {
    const Orig = window.RTCPeerConnection;
    if (!Orig) return;
    function Wrapped() {
      const pc = new Orig(...arguments);
      try {
        pc.addEventListener("track", (ev) => {
          if (ev && ev.track && ev.track.kind === "audio") {
            window.__meetCapturedTracks.push(ev.track);
            if (ev.streams && ev.streams.length) {
              for (const s of ev.streams) {
                s.addEventListener("addtrack", (e) => {
                  if (e.track && e.track.kind === "audio") {
                    window.__meetCapturedTracks.push(e.track);
                  }
                });
              }
            }
          }
        });
      } catch (e) {}
      return pc;
    }
    Wrapped.prototype = Orig.prototype;
    Object.setPrototypeOf(Wrapped, Orig);
    window.RTCPeerConnection = Wrapped;
  } catch (e) {}
})();
"""


def _looks_like_wall(text: str) -> bool:
    lowered = text.lower()
    return (
        "can't join this video call" in lowered
        or "ご参加いただけません" in text
        or "参加できません" in text
    )


class MeetAdmissionError(RuntimeError):
    """Raised when admission to the meeting cannot be confirmed."""


class MeetAntiBotWallError(MeetAdmissionError):
    """Raised when Meet shows the anti-bot ``You can't join`` wall."""


class MeetAudioSource:
    """One Meet meeting × one Chrome session × one audio stream."""

    def __init__(
        self,
        *,
        meet_url: str,
        bot_name: str = "DELTA AI",
        profile_dir: str | None = None,
        chrome_channel: str = "chrome",
        headless: bool = False,
        admission_timeout: float = 180.0,
        queue_size: int = 256,
    ) -> None:
        if not meet_url.startswith("https://meet.google.com/"):
            # Allow bare codes by upgrading to a full URL for navigation.
            if "/" in meet_url or " " in meet_url:
                raise ValueError(
                    f"meet_url must be a meet.google.com URL or a meeting code, got {meet_url!r}"
                )
            meet_url = f"https://meet.google.com/{meet_url}"
        self._meet_url = meet_url
        self._bot_name = bot_name
        self._profile_dir = profile_dir
        self._chrome_channel = chrome_channel
        self._headless = headless
        self._admission_timeout = admission_timeout

        self._events: asyncio.Queue[AudioEvent | None] = asyncio.Queue(maxsize=queue_size)
        self._closed = False
        self._pw = None
        self._context = None
        self._page = None
        self._ephemeral_profile_dir: str | None = None
        # Speaker cache so we don't re-emit identical names.
        self._last_speaker: str | None = None
        self._stats_task: asyncio.Task | None = None

    # ----- Public surface ----------------------------------------------------

    async def join(self) -> None:
        """Launch Chrome, navigate to Meet, run the humanlike join sequence.

        Emits status events along the way. Raises on hard failures (anti-bot
        wall, admission timeout). Returns once the bridge is installed and
        ready to fire audio events.
        """
        from playwright.async_api import async_playwright

        await self._emit_status("joining", "launching chromium")

        self._pw = await async_playwright().start()

        profile_dir = self._profile_dir
        if not profile_dir:
            self._ephemeral_profile_dir = tempfile.mkdtemp(prefix="meet-bot-profile-")
            profile_dir = self._ephemeral_profile_dir
        os.makedirs(profile_dir, exist_ok=True)

        self._context = await self._pw.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            channel=self._chrome_channel,
            headless=self._headless,
            args=list(_DEFAULT_CHROME_ARGS),
            ignore_default_args=list(_DEFAULT_IGNORE_DEFAULT_ARGS),
            no_viewport=True,
        )

        # Defensive navigator.webdriver override — installed before any nav.
        await self._context.add_init_script(_WEBDRIVER_OVERRIDE_JS)
        # Pre-nav RTC constructor wrap so Meet's PCs (created during join
        # handshake) deposit their inbound audio tracks into a global array
        # the main bridge picks up after admission.
        await self._context.add_init_script(_PRE_NAV_RTC_WRAP_JS)

        pages = self._context.pages
        page = pages[0] if pages else await self._context.new_page()
        self._page = page

        await self._emit_status("joining", f"navigating to {self._meet_url}")
        try:
            await page.goto(self._meet_url, wait_until="domcontentloaded", timeout=30_000)
        except Exception as exc:
            raise MeetAdmissionError(f"goto failed: {exc!r}") from exc

        # Give the pre-join screen a beat to render.
        await asyncio.sleep(3.0)

        wall_text = await page.evaluate(_WALL_TEXT_JS)
        if _looks_like_wall(wall_text):
            raise MeetAntiBotWallError(
                "Meet showed the 'You can't join this video call' wall — "
                "anti-bot rejected the session"
            )

        await self._best_effort_mute_devices()
        await self._best_effort_set_name()
        await self._best_effort_click_join()
        await self._wait_for_admission()

        # Post-admission bridge install. Order matters: the script must be
        # in place BEFORE we call expose_function from Python, otherwise the
        # binding races with the first PCM emission.
        bootstrap_js = _BOOTSTRAP_PATH.read_text(encoding="utf-8")
        await self._context.add_init_script(bootstrap_js)
        await page.expose_function("meetAudioOnPcm", self._on_pcm_b64)
        await page.expose_function("meetSpeakerOnUpdate", self._on_speaker_name)
        await page.evaluate(bootstrap_js)

        await self._emit_status("joined", "bridge installed; awaiting audio")
        logger.info("meet_audio_source: joined topic, bridge installed")
        # Start a background task that polls the in-page bridge stats so we
        # can see (from logs) whether PCs / tracks / chunks are flowing.
        self._stats_task = asyncio.create_task(
            self._poll_bridge_stats(), name="bridge-stats"
        )

    def events(self) -> AsyncIterator[AudioEvent]:
        """Async iterator over audio + speaker + status events.

        Terminates when :meth:`close` is called.
        """
        return self._event_iterator()

    async def _event_iterator(self) -> AsyncIterator[AudioEvent]:
        while True:
            ev = await self._events.get()
            if ev is None:
                return
            yield ev

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._stats_task is not None:
            self._stats_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._stats_task
            self._stats_task = None
        await self._emit_status("left", "closing")
        # Sentinel so iterator wakes and exits.
        with contextlib.suppress(asyncio.QueueFull):
            self._events.put_nowait(None)

        for name, closer in (
            ("page", self._page),
            ("context", self._context),
        ):
            if closer is None:
                continue
            try:
                await closer.close()
            except Exception:  # noqa: BLE001
                logger.exception("close %s raised", name)

        if self._ephemeral_profile_dir:
            import shutil
            with contextlib.suppress(Exception):
                shutil.rmtree(self._ephemeral_profile_dir, ignore_errors=True)

        if self._pw is not None:
            with contextlib.suppress(Exception):
                await self._pw.stop()

    # ----- Bridge callbacks (called from JS via expose_function) ------------

    async def _on_pcm_b64(self, b64: str, sample_rate: int) -> None:
        if self._closed:
            return
        try:
            data = base64.b64decode(b64)
        except Exception as exc:  # noqa: BLE001
            logger.debug("bad PCM base64: %s", exc)
            return
        ev = AudioEvent(kind="pcm", data=data, sample_rate=int(sample_rate))
        await self._enqueue(ev)

    async def _poll_bridge_stats(self) -> None:
        """Log bridge stats only when they CHANGE — quiet by default.

        Also takes periodic screenshots so we can see what Meet is showing
        when audio fails to arrive.
        """
        import os as _os
        prev_summary: tuple | None = None
        shot_dir = _os.environ.get("BOT_SHOT_DIR", "/tmp/bot-shots")
        try:
            _os.makedirs(shot_dir, exist_ok=True)
        except Exception:  # noqa: BLE001
            pass
        shot_idx = 0
        last_shot_at = 0.0
        while not self._closed and self._page is not None:
            try:
                stats = await self._page.evaluate(
                    "() => window.__meetAudioStats && window.__meetAudioStats()"
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("bridge stats evaluate failed: %s", exc)
                stats = None
            try:
                probe = await self._page.evaluate(
                    "() => window.__meetAudioProbeDom && window.__meetAudioProbeDom()"
                )
            except Exception:  # noqa: BLE001
                probe = None
            try:
                track_info = await self._page.evaluate(
                    "() => window.__meetTrackInfo && window.__meetTrackInfo()"
                )
            except Exception:  # noqa: BLE001
                track_info = None

            summary = None
            if stats and probe:
                tracks_summary = None
                if track_info:
                    tracks_summary = tuple(
                        (t.get("muted"), t.get("enabled"), t.get("unmute_count"))
                        for t in track_info
                    )
                summary = (
                    stats.get("audio_context_state"),
                    stats.get("worklet_loaded"),
                    stats.get("pcs_constructed"),
                    stats.get("audio_tracks_seen"),
                    probe.get("audio_count"),
                    probe.get("video_count"),
                    tracks_summary,
                )
            if summary != prev_summary:
                if stats:
                    logger.info(
                        "bridge_stats: ctx=%s worklet=%s pcs=%s audio_tracks=%s chunks=%s last_err=%s",
                        stats.get("audio_context_state"),
                        stats.get("worklet_loaded"),
                        stats.get("pcs_constructed"),
                        stats.get("audio_tracks_seen"),
                        stats.get("chunks_sent"),
                        stats.get("last_error"),
                    )
                if probe:
                    logger.info(
                        "dom_probe: <audio>=%s <video>=%s",
                        probe.get("audio_count"),
                        probe.get("video_count"),
                    )
                if track_info:
                    logger.info("track_info: %s", track_info)
                prev_summary = summary

            # Periodic screenshot every 15s.
            now = asyncio.get_event_loop().time()
            if now - last_shot_at > 15:
                path = f"{shot_dir}/{int(now)}_{shot_idx:03d}.png"
                shot_idx += 1
                try:
                    await self._page.screenshot(path=path, full_page=False)
                    logger.info("screenshot: %s", path)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("screenshot failed: %s", exc)
                last_shot_at = now

            await asyncio.sleep(3.0)

    async def _on_speaker_name(self, name: str) -> None:
        if self._closed:
            return
        # Empty string from JS means "nobody is talking right now". Normalize.
        normalized: str | None = name.strip() if name else None
        if normalized == self._last_speaker:
            return
        self._last_speaker = normalized
        await self._enqueue(AudioEvent(kind="speaker", speaker_name=normalized))

    # ----- Internal ---------------------------------------------------------

    async def _emit_status(self, state: str, detail: str | None = None) -> None:
        await self._enqueue(AudioEvent(kind="status", state=state, detail=detail))

    async def _enqueue(self, ev: AudioEvent) -> None:
        try:
            self._events.put_nowait(ev)
        except asyncio.QueueFull:
            # Drop the oldest PCM frame to favor freshness; this matches the
            # posture-feedback pattern. Status / speaker events are tiny so
            # we let them queue beyond their slot if PCM is the bottleneck.
            with contextlib.suppress(asyncio.QueueEmpty):
                _ = self._events.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                self._events.put_nowait(ev)

    # ----- Humanlike interaction (CDP-driven) -------------------------------

    async def _human_pause(self, lo: float = 0.08, hi: float = 0.22) -> None:
        await asyncio.sleep(random.uniform(lo, hi))

    async def _humanlike_click_rect(self, rect: dict[str, float]) -> None:
        page = self._page
        assert page is not None
        tx = rect["x"] + random.uniform(-rect["w"] / 6, rect["w"] / 6)
        ty = rect["y"] + random.uniform(-rect["h"] / 6, rect["h"] / 6)
        await page.mouse.move(tx, ty, steps=random.randint(8, 16))
        await self._human_pause(0.10, 0.25)
        await page.mouse.click(tx, ty, delay=random.randint(40, 110))

    async def _locate_rect(self, selector: str) -> dict[str, float] | None:
        page = self._page
        assert page is not None
        try:
            return await page.evaluate(_LOCATE_RECT_JS, selector)
        except Exception as exc:  # noqa: BLE001
            logger.debug("locate %s failed: %s", selector, exc)
            return None

    async def _locate_button_by_text(self, labels: list[str]) -> dict[str, float] | None:
        page = self._page
        assert page is not None
        try:
            return await page.evaluate(_LOCATE_BUTTON_BY_TEXT_JS, labels)
        except Exception as exc:  # noqa: BLE001
            logger.debug("locate button by text failed: %s", exc)
            return None

    async def _best_effort_mute_devices(self) -> None:
        for kw in ("microphone", "マイク", "camera", "カメラ"):
            rect = await self._locate_rect(
                f'[data-is-muted="false"][aria-label*="{kw}" i]'
            )
            if rect is None:
                continue
            try:
                await self._humanlike_click_rect(rect)
                logger.info("muted %s", kw)
                await self._human_pause(0.15, 0.40)
            except Exception as exc:  # noqa: BLE001
                logger.debug("mute %s failed: %s", kw, exc)

    async def _best_effort_set_name(self) -> None:
        page = self._page
        assert page is not None
        for selector in (
            'input[aria-label="Your name"]',
            'input[aria-label="あなたの名前"]',
            'input[placeholder="Your name"]',
            'input[placeholder="あなたの名前"]',
            'input[aria-label*="name" i]',
            'input[aria-label*="名前"]',
        ):
            rect = await self._locate_rect(selector)
            if rect is None:
                continue
            try:
                await self._humanlike_click_rect(rect)
                await self._human_pause(0.08, 0.18)
                await page.keyboard.press("Control+A")
                await self._human_pause(0.05, 0.12)
                await page.keyboard.press("Delete")
                await self._human_pause(0.08, 0.18)
                # Char-by-char with jitter — anti-bot inspects this.
                for ch in self._bot_name:
                    await page.keyboard.type(ch)
                    await asyncio.sleep(random.uniform(0.05, 0.16))
                logger.info("set bot name to %r", self._bot_name)
                await self._human_pause(0.20, 0.45)
                return
            except Exception as exc:  # noqa: BLE001
                logger.debug("set name via %s failed: %s", selector, exc)

    async def _best_effort_click_join(self) -> None:
        rect = await self._locate_button_by_text(
            ["ask to join", "join now", "参加をリクエスト", "今すぐ参加", "参加"]
        )
        if rect is None:
            logger.info("join button not found")
            return
        try:
            await self._humanlike_click_rect(rect)
            logger.info("clicked join at (%.0f, %.0f)", rect["x"], rect["y"])
        except Exception as exc:  # noqa: BLE001
            logger.debug("click join failed: %s", exc)

    async def _wait_for_admission(self) -> None:
        page = self._page
        assert page is not None
        deadline = asyncio.get_event_loop().time() + self._admission_timeout
        last_log = 0.0
        while True:
            try:
                admitted = await page.evaluate(_ADMITTED_PROBE_JS)
            except Exception:  # noqa: BLE001
                admitted = False
            if admitted:
                return
            now = asyncio.get_event_loop().time()
            if now > deadline:
                # Final check: was it the wall instead of a slow host?
                wall_text = await page.evaluate(_WALL_TEXT_JS)
                if _looks_like_wall(wall_text):
                    raise MeetAntiBotWallError(
                        "admission_timeout + wall detected post-click — anti-bot"
                    )
                raise MeetAdmissionError(
                    f"admission_timeout after {self._admission_timeout:.0f}s "
                    "(host did not admit, or pre-join interaction failed)"
                )
            if now - last_log > 15:
                logger.info("still waiting for admission (%.0fs left)", deadline - now)
                last_log = now
            await asyncio.sleep(2.0)
