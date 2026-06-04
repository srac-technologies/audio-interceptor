"""Phase 0 spike: in-page Web Audio API capture from Google Meet without stealth.

Goal: verify whether plain Playwright (NOT Patchright) + autoplay flags + a
RTCPeerConnection prototype patch installed BEFORE join can join a Meet and
receive Int16 PCM continuously for ~60s. If this works we can build the bot
on plain Playwright with in-page audio extraction; if Meet rejects us, we
fall back to Patchright stealth + PulseAudio sink (see plan, Phase 0).

Usage:
    python spike_audio.py \\
        --meet-url https://meet.google.com/xxx-yyyy-zzz \\
        --profile-dir /tmp/meet-spike-profile \\
        --duration 60

The first run will use an empty profile; you can manually sign in to Google
in the launched browser (then close the browser) so subsequent runs auto-join
as that account. The bot still has to be admitted by an in-call host unless
the meeting allows quick access.

The script writes captured PCM to spike_audio_<timestamp>.wav and prints a
short report (total seconds, sample-rate, number of empty chunks).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import json
import logging
import os
import random
import struct
import sys
import time
import wave
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("spike_audio")


# In-page bootstrap. Installed via add_init_script BEFORE navigation so the
# RTCPeerConnection constructor wrap is in place during Meet's join handshake.
# This is the riskiest pattern w.r.t. anti-bot — that's exactly what we want
# to measure.
_BOOTSTRAP_JS = r"""
(() => {
  if (window.__meetAudioBridgeInstalled) return;
  window.__meetAudioBridgeInstalled = true;

  // Diagnostics counters surfaced to Python via window.__meetAudioStats().
  const stats = {
    pcs_constructed: 0,
    tracks_attached: 0,
    audio_tracks_seen: 0,
    chunks_sent: 0,
    last_error: null,
    audio_context_state: "uninitialized",
    audio_context_rate: 0,
  };
  window.__meetAudioStats = () => JSON.parse(JSON.stringify(stats));

  // Lazy: only create the AudioContext on the first track so that we don't
  // touch the audio subsystem before user activation. The join button click
  // counts as activation in headed mode.
  let audioCtx = null;
  let mixer = null;

  function ensureAudioContext() {
    if (audioCtx) return audioCtx;
    try {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      stats.audio_context_rate = audioCtx.sampleRate;
      stats.audio_context_state = audioCtx.state;

      // Mixer node: every inbound MediaStreamSource is connected here.
      mixer = audioCtx.createGain();
      mixer.gain.value = 1.0;

      // ScriptProcessorNode is deprecated but vastly simpler than AudioWorklet
      // for a spike. 4096-sample buffer @ 48 kHz ≈ 85 ms.
      const proc = audioCtx.createScriptProcessor(4096, 1, 1);
      proc.onaudioprocess = (ev) => {
        const input = ev.inputBuffer.getChannelData(0);
        // Convert Float32 [-1, 1] to Int16 little-endian.
        const out = new Int16Array(input.length);
        for (let i = 0; i < input.length; i++) {
          let s = Math.max(-1, Math.min(1, input[i]));
          out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
        const bytes = new Uint8Array(out.buffer);
        // base64 encode in chunks to avoid call-stack issues on big arrays.
        let bin = "";
        const CHUNK = 0x8000;
        for (let i = 0; i < bytes.length; i += CHUNK) {
          bin += String.fromCharCode.apply(
            null, bytes.subarray(i, i + CHUNK),
          );
        }
        const b64 = btoa(bin);
        try {
          window.meetAudioOnPcm(b64, audioCtx.sampleRate);
          stats.chunks_sent += 1;
        } catch (e) {
          stats.last_error = String(e);
        }
      };
      mixer.connect(proc);
      // ScriptProcessor needs to be connected to a destination to actually
      // run onaudioprocess. We route through a zero-gain node so it doesn't
      // affect the user-audible output.
      const sink = audioCtx.createGain();
      sink.gain.value = 0.0;
      proc.connect(sink);
      sink.connect(audioCtx.destination);

      // Resume aggressively in case it lands suspended.
      const tryResume = () => {
        if (audioCtx.state !== "running") {
          audioCtx.resume().catch(() => {});
        }
        stats.audio_context_state = audioCtx.state;
      };
      tryResume();
      setInterval(tryResume, 1000);
    } catch (e) {
      stats.last_error = "audioctx_init: " + String(e);
    }
    return audioCtx;
  }

  function pipeTrack(track) {
    if (!track || track.kind !== "audio") return;
    stats.audio_tracks_seen += 1;
    const ctx = ensureAudioContext();
    if (!ctx || !mixer) return;
    try {
      const ms = new MediaStream([track]);
      const src = ctx.createMediaStreamSource(ms);
      src.connect(mixer);
    } catch (e) {
      stats.last_error = "pipeTrack: " + String(e);
    }
  }

  // Wrap the RTCPeerConnection constructor so that every PC instance gets a
  // 'track' listener installed for inbound audio. This is the most reliable
  // hook because Meet establishes audio long before any <audio> element is
  // visible in the DOM.
  if (window.RTCPeerConnection && !window.RTCPeerConnection.__meetAudioWrapped) {
    const OrigPC = window.RTCPeerConnection;
    function WrappedPC() {
      const pc = new OrigPC(...arguments);
      stats.pcs_constructed += 1;
      try {
        pc.addEventListener("track", (ev) => {
          stats.tracks_attached += 1;
          pipeTrack(ev.track);
          // Also handle tracks added to the stream later.
          if (ev.streams && ev.streams.length) {
            for (const stream of ev.streams) {
              stream.addEventListener("addtrack", (e) => pipeTrack(e.track));
            }
          }
        });
      } catch (e) {
        stats.last_error = "pc_listener: " + String(e);
      }
      return pc;
    }
    WrappedPC.prototype = OrigPC.prototype;
    WrappedPC.__meetAudioWrapped = true;
    // Preserve static helpers (generateCertificate etc).
    Object.setPrototypeOf(WrappedPC, OrigPC);
    window.RTCPeerConnection = WrappedPC;
  }

  // Best-effort fallback: also watch DOM for <audio> elements (some clients
  // route through them) and connect their srcObject streams.
  const seen = new WeakSet();
  function adoptAudioEl(el) {
    if (seen.has(el)) return;
    seen.add(el);
    const tryAttach = () => {
      const stream = el.srcObject;
      if (stream && stream.getAudioTracks) {
        for (const t of stream.getAudioTracks()) {
          pipeTrack(t);
        }
      }
    };
    tryAttach();
    el.addEventListener("loadedmetadata", tryAttach);
  }
  try {
    const mo = new MutationObserver((muts) => {
      for (const m of muts) {
        for (const n of m.addedNodes || []) {
          if (n.nodeType === 1) {
            if (n.tagName === "AUDIO") adoptAudioEl(n);
            n.querySelectorAll && n.querySelectorAll("audio").forEach(adoptAudioEl);
          }
        }
      }
    });
    mo.observe(document.documentElement, { childList: true, subtree: true });
    document.querySelectorAll && document.querySelectorAll("audio").forEach(adoptAudioEl);
  } catch (e) {
    stats.last_error = "mutation_observer: " + String(e);
  }
})();
"""


# JS helper to locate a clickable element by CSS selector AND return its
# bounding-box center. Python then drives a real CDP mouse move + click —
# never a JS .click() — because Meet's anti-bot inspects event.isTrusted
# and the pre-click pointer history.
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

# Locate a button by *text content* (case-insensitive substring match across
# any of the supplied labels). Useful for the Meet "Ask to join" / "Join now"
# / Japanese variants whose CSS class names rotate but whose visible text is
# stable.
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
      return {
        x: r.left + r.width / 2,
        y: r.top + r.height / 2,
        w: r.width,
        h: r.height,
      };
    }
  }
  return null;
}
"""


@dataclass
class SpikeReport:
    started_at: str
    duration_target_s: float
    pcm_bytes_received: int = 0
    chunks_received: int = 0
    sample_rate_seen: int | None = None
    first_chunk_at_s: float | None = None
    last_chunk_at_s: float | None = None
    js_stats: dict | None = None
    join_admitted: bool = False
    shots_taken: int = 0
    notes: list[str] = field(default_factory=list)


async def main(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.driver == "patchright":
        try:
            from patchright.async_api import async_playwright  # type: ignore
            logger.info("using patchright (stealth)")
        except ImportError:
            logger.error("patchright is not installed in this venv")
            return 2
    else:
        from playwright.async_api import async_playwright
        logger.info("using plain playwright")

    report = SpikeReport(
        started_at=datetime.utcnow().isoformat() + "Z",
        duration_target_s=args.duration,
    )
    start_wall = time.time()

    # Prepare WAV writer lazily once we know the sample rate.
    wav_path = os.path.abspath(args.wav_out)
    wav: wave.Wave_write | None = None
    sample_rate_seen: int | None = None

    pcm_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=512)

    async def on_pcm(b64: str, sample_rate: int) -> None:
        nonlocal sample_rate_seen
        try:
            data = base64.b64decode(b64)
        except Exception as exc:  # noqa: BLE001
            logger.warning("bad base64: %s", exc)
            return
        if sample_rate_seen is None:
            sample_rate_seen = sample_rate
            report.sample_rate_seen = sample_rate
            logger.info("first PCM chunk: %d bytes @ %d Hz", len(data), sample_rate)
        await pcm_queue.put(data)

    async def writer_task() -> None:
        nonlocal wav
        while True:
            chunk = await pcm_queue.get()
            if chunk is None:
                return
            if wav is None:
                if sample_rate_seen is None:
                    continue
                wav = wave.open(wav_path, "wb")
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sample_rate_seen)
                logger.info("opened wav: %s @ %d Hz", wav_path, sample_rate_seen)
            wav.writeframes(chunk)
            report.pcm_bytes_received += len(chunk)
            report.chunks_received += 1
            now = time.time() - start_wall
            if report.first_chunk_at_s is None:
                report.first_chunk_at_s = now
            report.last_chunk_at_s = now

    writer = asyncio.create_task(writer_task())

    async with async_playwright() as pw:
        chrome_args = [
            "--autoplay-policy=no-user-gesture-required",
            # Stops Chromium from setting navigator.webdriver=true, removing
            # the single most reliable bot-detection signal.
            "--disable-blink-features=AutomationControlled",
            # Hide Playwright's "Chrome is being controlled by automated test
            # software" infobar and the associated chrome.runtime quirks.
            "--disable-infobars",
            # We do NOT pass --use-fake-ui-for-media-stream: the bot consumes
            # remote audio tracks, it doesn't grant local mic/cam.
        ]
        # Playwright defaults inject --enable-automation and a few other
        # markers that Meet keys on. Drop them. (Patchright does the same
        # internally; this is the plain-Playwright equivalent.)
        ignore_default_args = [
            "--enable-automation",
            "--enable-blink-features=IdleDetection",
        ]
        logger.info(
            "launching Chromium (plain Playwright, NOT patchright); inject_when=%s",
            args.inject_when,
        )
        os.makedirs(args.profile_dir, exist_ok=True)
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=args.profile_dir,
            channel=args.channel,
            headless=False,  # always headed for the spike
            args=chrome_args,
            ignore_default_args=ignore_default_args,
            no_viewport=True,
        )

        # Defensive: even with --disable-blink-features=AutomationControlled
        # there are edge cases where navigator.webdriver re-appears. Override
        # it via add_init_script BEFORE any page navigation. This script is
        # tiny and matches what every stealth library ships, so its presence
        # is itself a known-good baseline rather than a unique fingerprint.
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )

        if args.inject_when == "pre":
            # Risky: the RTCPeerConnection constructor wrap + the exposed
            # binding are in place during Meet's join handshake. This is
            # exactly the pattern posture-feedback documents as triggering
            # the "You can't join this video call" wall.
            await context.add_init_script(_BOOTSTRAP_JS)

        pages = context.pages
        page = pages[0] if pages else await context.new_page()

        if args.inject_when == "pre":
            await page.expose_function("meetAudioOnPcm", on_pcm)

        # ----- Humanlike interaction helpers -------------------------------
        # These mirror posture-feedback/meeting_bot.py:472-565 — real CDP
        # mouse moves + clicks + per-character keyboard.type with random
        # jitter, instead of JS-driven .click() / .value=. Meet's anti-bot
        # inspects event.isTrusted, pre-click pointer history, and
        # inter-keystroke variance to spot bots.

        async def human_pause(lo: float = 0.08, hi: float = 0.22) -> None:
            await asyncio.sleep(random.uniform(lo, hi))

        async def humanlike_click_rect(rect: dict) -> None:
            tx = rect["x"] + random.uniform(-rect["w"] / 6, rect["w"] / 6)
            ty = rect["y"] + random.uniform(-rect["h"] / 6, rect["h"] / 6)
            await page.mouse.move(tx, ty, steps=random.randint(8, 16))
            await human_pause(0.10, 0.25)
            await page.mouse.click(tx, ty, delay=random.randint(40, 110))

        async def locate_rect(selector: str) -> dict | None:
            try:
                return await page.evaluate(_LOCATE_RECT_JS, selector)
            except Exception as exc:  # noqa: BLE001
                logger.debug("locate %s failed: %s", selector, exc)
                return None

        async def locate_button_by_text(labels: list[str]) -> dict | None:
            try:
                return await page.evaluate(_LOCATE_BUTTON_BY_TEXT_JS, labels)
            except Exception as exc:  # noqa: BLE001
                logger.debug("locate_button_by_text failed: %s", exc)
                return None

        async def best_effort_mute_devices() -> dict:
            result = {"mic": False, "cam": False}
            # posture-feedback uses [data-is-muted="false"] which is the
            # most reliable Meet selector for pre-join unmuted devices.
            for kind, kw in [
                ("mic", "microphone"), ("mic", "マイク"),
                ("cam", "camera"), ("cam", "カメラ"),
            ]:
                if result[kind]:
                    continue
                rect = await locate_rect(
                    f'[data-is-muted="false"][aria-label*="{kw}" i]'
                )
                if rect is None:
                    continue
                try:
                    await humanlike_click_rect(rect)
                    result[kind] = True
                    logger.info("muted %s (kw=%s)", kind, kw)
                    await human_pause(0.15, 0.40)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("mute %s failed: %s", kw, exc)
            return result

        async def best_effort_set_name() -> bool:
            for selector in (
                'input[aria-label="Your name"]',
                'input[aria-label="あなたの名前"]',
                'input[placeholder="Your name"]',
                'input[placeholder="あなたの名前"]',
                'input[aria-label*="name" i]',
                'input[aria-label*="名前"]',
            ):
                rect = await locate_rect(selector)
                if rect is None:
                    continue
                try:
                    await humanlike_click_rect(rect)
                    await human_pause(0.08, 0.18)
                    await page.keyboard.press("Control+A")
                    await human_pause(0.05, 0.12)
                    await page.keyboard.press("Delete")
                    await human_pause(0.08, 0.18)
                    # Character by character with jitter — DO NOT use
                    # input.value = "...": Meet sniffs inter-keystroke
                    # variance.
                    for ch in args.bot_name:
                        await page.keyboard.type(ch)
                        await asyncio.sleep(random.uniform(0.05, 0.16))
                    logger.info("set bot name to %r via %s", args.bot_name, selector)
                    await human_pause(0.20, 0.45)
                    return True
                except Exception as exc:  # noqa: BLE001
                    logger.debug("set name via %s failed: %s", selector, exc)
            return False

        async def best_effort_click_join() -> bool:
            rect = await locate_button_by_text([
                "ask to join", "join now", "参加をリクエスト", "今すぐ参加", "参加",
            ])
            if rect is None:
                logger.info("join button not found")
                return False
            try:
                await humanlike_click_rect(rect)
                logger.info("clicked join at (%.0f, %.0f)", rect["x"], rect["y"])
                return True
            except Exception as exc:  # noqa: BLE001
                logger.debug("click join failed: %s", exc)
                return False
        # -------------------------------------------------------------------

        logger.info("navigating to %s", args.meet_url)
        try:
            await page.goto(
                args.meet_url, wait_until="domcontentloaded", timeout=30000
            )
        except Exception as exc:  # noqa: BLE001
            report.notes.append(f"goto raised: {exc!r}")
            logger.exception("goto failed")

        # Give Meet a moment to render the pre-join screen.
        await asyncio.sleep(3)

        # Anti-bot wall check (page text scan).
        wall_text = await page.evaluate(
            "() => (document.body && document.body.innerText || '').slice(0, 4000)"
        )
        if "can't join this video call" in wall_text.lower() or \
           "ご参加いただけません" in wall_text or \
           "参加できません" in wall_text:
            report.notes.append("anti-bot wall detected on initial load")
            logger.error("anti-bot wall hit — Meet refused entry pre-join")

        # Humanlike pre-join flow: mute → set name → click join.
        mute_result = await best_effort_mute_devices()
        report.notes.append(f"mute: {mute_result}")
        name_set = await best_effort_set_name()
        report.notes.append(f"name_set: {name_set}")
        joined_clicked = await best_effort_click_join()
        report.notes.append(f"join_clicked: {joined_clicked}")

        # Wait for admission: <video> with non-zero dims OR a "Leave call"
        # button (Meet UI after admission).
        admitted = False
        admit_deadline = time.time() + args.admission_timeout
        last_status_log = 0.0
        while time.time() < admit_deadline:
            try:
                admitted = await page.evaluate(
                    """() => {
                        const videos = Array.from(document.querySelectorAll('video'));
                        if (videos.some(v => v.videoWidth > 0 && v.videoHeight > 0)) return true;
                        const buttons = Array.from(document.querySelectorAll('button, [role="button"]'));
                        for (const b of buttons) {
                          const label = (b.getAttribute('aria-label') || '').toLowerCase();
                          if (label.includes('leave call') || label.includes('通話を終了')) return true;
                        }
                        return false;
                    }"""
                )
            except Exception:  # noqa: BLE001
                admitted = False
            if admitted:
                break
            now = time.time()
            if now - last_status_log > 15:
                logger.info(
                    "still waiting for admission (%.0fs elapsed)",
                    now - start_wall,
                )
                last_status_log = now
            await asyncio.sleep(2)
        report.join_admitted = admitted
        logger.info("admitted=%s after %.1fs", admitted, time.time() - start_wall)
        if not admitted:
            report.notes.append("admission_timeout")

        # Post-admission injection path: install the bridge AFTER Meet has
        # already accepted us. Mirrors posture-feedback's pattern. Trade-off:
        # the RTCPeerConnection constructor wrap will NOT catch PCs that Meet
        # constructed during join, so we depend on the <audio> MutationObserver
        # fallback to pick up audio tracks.
        if args.inject_when == "post" and admitted:
            logger.info("installing audio bridge post-admission")
            await context.add_init_script(_BOOTSTRAP_JS)
            try:
                await page.expose_function("meetAudioOnPcm", on_pcm)
            except Exception as exc:  # noqa: BLE001
                logger.warning("expose_function (post) raised: %s", exc)
            await page.evaluate(_BOOTSTRAP_JS)

        # Screenshot helper — periodic snapshots so a headless/xvfb runner
        # can still see what Meet is showing post-mortem.
        shots_dir = args.shots_dir
        if shots_dir:
            os.makedirs(shots_dir, exist_ok=True)
        next_shot_at = time.time() if shots_dir else float("inf")

        async def take_shot(tag: str) -> None:
            if not shots_dir:
                return
            path = os.path.join(
                shots_dir, f"{int(time.time() - start_wall):04d}s_{tag}.png"
            )
            try:
                await page.screenshot(path=path, full_page=False)
                report.shots_taken += 1
                logger.info("shot: %s", path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("screenshot failed: %s", exc)

        # Pre-capture shots: one immediately after navigation/join attempt.
        await take_shot("post_join")

        # Drive the capture window: poll the in-page stats periodically and
        # let the writer task pull chunks until the duration elapses.
        capture_deadline = time.time() + args.duration
        while time.time() < capture_deadline:
            await asyncio.sleep(2)
            try:
                js_stats = await page.evaluate("() => window.__meetAudioStats && window.__meetAudioStats()")
            except Exception:  # noqa: BLE001
                js_stats = None
            if js_stats:
                report.js_stats = js_stats
                logger.info(
                    "stats: pcs=%s tracks_attached=%s audio_tracks=%s chunks=%s ctx=%s@%s last_err=%s",
                    js_stats.get("pcs_constructed"),
                    js_stats.get("tracks_attached"),
                    js_stats.get("audio_tracks_seen"),
                    js_stats.get("chunks_sent"),
                    js_stats.get("audio_context_state"),
                    js_stats.get("audio_context_rate"),
                    js_stats.get("last_error"),
                )
            if shots_dir and time.time() >= next_shot_at:
                await take_shot("periodic")
                next_shot_at = time.time() + max(1.0, args.shots_interval)

        await take_shot("final")

        with contextlib.suppress(Exception):
            await context.close()

    await pcm_queue.put(None)
    with contextlib.suppress(asyncio.CancelledError):
        await writer
    if wav is not None:
        wav.close()

    duration_s = time.time() - start_wall
    print("\n=== Spike Report ===")
    print(json.dumps(
        {
            "started_at": report.started_at,
            "duration_target_s": report.duration_target_s,
            "duration_actual_s": round(duration_s, 2),
            "join_admitted": report.join_admitted,
            "chunks_received": report.chunks_received,
            "pcm_bytes_received": report.pcm_bytes_received,
            "sample_rate_seen": report.sample_rate_seen,
            "first_chunk_at_s": report.first_chunk_at_s,
            "last_chunk_at_s": report.last_chunk_at_s,
            "wav_out": wav_path if report.pcm_bytes_received else None,
            "shots_dir": args.shots_dir if args.shots_dir else None,
            "shots_taken": report.shots_taken,
            "js_stats": report.js_stats,
            "notes": report.notes,
        },
        indent=2,
        ensure_ascii=False,
    ))
    # Exit non-zero if we couldn't get any audio so this can be used in CI.
    return 0 if report.pcm_bytes_received > 0 else 1


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--meet-url", required=True, help="https://meet.google.com/xxx-yyyy-zzz")
    p.add_argument(
        "--profile-dir",
        default=os.path.expanduser("~/.cache/meet-audio-spike-profile"),
        help="Persistent Chrome profile dir (sign in once, reuse).",
    )
    p.add_argument(
        "--channel",
        default="chrome",
        help="Chromium channel: 'chrome' (system Google Chrome) or 'chromium'.",
    )
    p.add_argument("--duration", type=float, default=60.0, help="Capture seconds after join.")
    p.add_argument(
        "--admission-timeout", type=float, default=180.0,
        help="How long to wait for admission to the meeting.",
    )
    p.add_argument(
        "--wav-out", default=f"spike_audio_{int(time.time())}.wav",
        help="Where to write captured PCM (16-bit mono).",
    )
    p.add_argument(
        "--shots-dir", default=None,
        help="Directory to save periodic screenshots (omit to disable).",
    )
    p.add_argument(
        "--shots-interval", type=float, default=5.0,
        help="Screenshot interval seconds (default: 5).",
    )
    p.add_argument(
        "--bot-name", default="Audio Spike Bot",
        help="Display name typed into the Meet pre-join screen.",
    )
    p.add_argument(
        "--inject-when", choices=("pre", "post"), default="post",
        help=(
            "When to inject the in-page audio bridge. 'pre': via "
            "add_init_script BEFORE goto (the risky path — RTCPeerConnection "
            "wrap catches every PC but is highly fingerprintable). 'post': "
            "only after Meet admits us (mirrors posture-feedback's pattern; "
            "relies on the <audio> MutationObserver fallback for audio)."
        ),
    )
    p.add_argument(
        "--driver", choices=("playwright", "patchright"), default="playwright",
        help=(
            "Which browser driver to use. 'playwright' = plain Playwright "
            "(with stealth-ish args). 'patchright' = the stealth fork used "
            "by posture-feedback. A/B these to isolate where Meet rejects."
        ),
    )
    return p.parse_args()


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main(parse_args())))
    except KeyboardInterrupt:
        sys.exit(130)
