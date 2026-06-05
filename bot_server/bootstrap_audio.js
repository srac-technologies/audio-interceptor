/* eslint-disable */
/**
 * In-page audio bridge for the Meet bot.
 *
 * Loaded *post-admission* via `add_init_script` + `page.evaluate`. This is
 * the only injection mode that survives Meet's anti-bot — see
 * /home/tan_t/.claude/projects/-home-tan-t-workspace-audio-interceptor/memory/feedback_meet_bot_stealth.md
 * for the empirical receipts.
 *
 * Architecture:
 *  - Wraps `RTCPeerConnection` constructor so future PCs route their inbound
 *    audio tracks through our AudioContext. (Existing PCs are caught by the
 *    <audio> MutationObserver fallback below; in practice Meet renumbers
 *    audio sinks frequently enough that both paths fire.)
 *  - AudioWorklet drains Float32 PCM at the context's native rate, posts
 *    chunks to the main thread, which encodes Int16 → base64 → calls
 *    `window.meetAudioOnPcm(b64, sampleRate)` exposed from Python.
 *  - A 5 Hz DOM poll surfaces the active speaker name through
 *    `window.meetSpeakerOnUpdate(name)` for transcript attribution.
 */
(() => {
  if (window.__meetAudioBridgeInstalled) return;
  window.__meetAudioBridgeInstalled = true;

  const stats = {
    pcs_constructed: 0,
    tracks_attached: 0,
    audio_tracks_seen: 0,
    chunks_sent: 0,
    last_error: null,
    audio_context_state: "uninitialized",
    audio_context_rate: 0,
    worklet_loaded: false,
    speaker_last: null,
    speaker_updates: 0,
  };
  window.__meetAudioStats = () => JSON.parse(JSON.stringify(stats));

  // DOM probe — call from Python to see what audio surfaces Meet exposes.
  window.__meetAudioProbeDom = () => {
    const audios = Array.from(document.querySelectorAll("audio"));
    const videos = Array.from(document.querySelectorAll("video"));
    return {
      audio_count: audios.length,
      video_count: videos.length,
      audios: audios.slice(0, 8).map((el) => ({
        has_src_object: !!el.srcObject,
        track_count: el.srcObject && el.srcObject.getAudioTracks
          ? el.srcObject.getAudioTracks().length : 0,
        muted: el.muted,
        paused: el.paused,
        readyState: el.readyState,
        autoplay: el.autoplay,
      })),
      videos_with_audio: videos.slice(0, 8).map((el) => ({
        has_src_object: !!el.srcObject,
        audio_track_count: el.srcObject && el.srcObject.getAudioTracks
          ? el.srcObject.getAudioTracks().length : 0,
      })),
    };
  };

  // Tunable from Python via `window.__meetAudioConfig`. Defaults here match
  // what worker.py asks for at startup; explicit overrides happen via a
  // page.evaluate call.
  const cfg = (window.__meetAudioConfig = window.__meetAudioConfig || {
    // Chunk size in samples at the context rate. 4096 @ 48 kHz ≈ 85 ms,
    // ~42 KB/s of PCM over the expose_function bridge per stream.
    chunk_samples: 4096,
    // Polling cadence for the active-speaker DOM scan.
    speaker_poll_hz: 5,
  });

  let audioCtx = null;
  let mixer = null;
  let workletNode = null;
  let workletReadyPromise = null;

  // ----- AudioWorklet plumbing ------------------------------------------
  // We register a tiny processor that forwards the input channel to the main
  // thread AND writes silence to its single mono output. The output is
  // required: a Web Audio node with numberOfOutputs=0 may be GCed / not
  // scheduled when nothing downstream pulls it. We route the silent output
  // through a zero-gain sink to ``audioCtx.destination`` so the graph treats
  // the worklet as a live producer.
  const WORKLET_SRC = `
    class PCMCaptureProcessor extends AudioWorkletProcessor {
      constructor(options) {
        super();
        this._chunk = options.processorOptions.chunkSamples || 4096;
        this._buf = new Float32Array(this._chunk);
        this._idx = 0;
      }
      process(inputs, outputs) {
        const input = inputs[0];
        // Write silence to output[0] mono so the graph keeps us alive.
        const output = outputs[0];
        if (output && output[0]) {
          output[0].fill(0);
        }
        if (!input || input.length === 0) return true;
        const channels = input;
        const samples = channels[0].length;
        const out = new Float32Array(samples);
        for (let c = 0; c < channels.length; c++) {
          const ch = channels[c];
          for (let i = 0; i < samples; i++) out[i] += ch[i];
        }
        if (channels.length > 1) {
          const inv = 1 / channels.length;
          for (let i = 0; i < samples; i++) out[i] *= inv;
        }
        for (let i = 0; i < samples; i++) {
          this._buf[this._idx++] = out[i];
          if (this._idx >= this._chunk) {
            const copy = this._buf.slice(0);
            this.port.postMessage(copy.buffer, [copy.buffer]);
            this._idx = 0;
          }
        }
        return true;
      }
    }
    registerProcessor('pcm-capture', PCMCaptureProcessor);
  `;

  async function ensureAudioContext() {
    if (audioCtx) return audioCtx;
    try {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      stats.audio_context_rate = audioCtx.sampleRate;
      stats.audio_context_state = audioCtx.state;

      mixer = audioCtx.createGain();
      mixer.gain.value = 1.0;

      const blob = new Blob([WORKLET_SRC], { type: "application/javascript" });
      const url = URL.createObjectURL(blob);
      workletReadyPromise = audioCtx.audioWorklet.addModule(url).then(() => {
        workletNode = new AudioWorkletNode(audioCtx, "pcm-capture", {
          processorOptions: { chunkSamples: cfg.chunk_samples },
          numberOfInputs: 1,
          numberOfOutputs: 1,
          outputChannelCount: [1],
        });
        workletNode.port.onmessage = (ev) => {
          // ev.data is an ArrayBuffer of Float32 PCM at audioCtx.sampleRate.
          const f32 = new Float32Array(ev.data);
          const int16 = new Int16Array(f32.length);
          for (let i = 0; i < f32.length; i++) {
            const s = Math.max(-1, Math.min(1, f32[i]));
            int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
          }
          // Base64-encode in slabs so big arrays don't blow the call stack.
          const bytes = new Uint8Array(int16.buffer);
          let bin = "";
          const SLAB = 0x8000;
          for (let i = 0; i < bytes.length; i += SLAB) {
            bin += String.fromCharCode.apply(null, bytes.subarray(i, i + SLAB));
          }
          const b64 = btoa(bin);
          try {
            window.meetAudioOnPcm(b64, audioCtx.sampleRate);
            stats.chunks_sent += 1;
          } catch (e) {
            stats.last_error = "onPcm: " + String(e);
          }
        };
        mixer.connect(workletNode);
        // Keep the worklet alive in the graph by giving it a downstream
        // path: zero-gain sink → destination. Web Audio prunes producers
        // that have nowhere to send their output.
        const sink = audioCtx.createGain();
        sink.gain.value = 0.0;
        workletNode.connect(sink);
        sink.connect(audioCtx.destination);
        stats.worklet_loaded = true;
        URL.revokeObjectURL(url);
      }).catch((e) => {
        stats.last_error = "worklet_load: " + String(e);
      });

      // Aggressive resume in case the AudioContext lands suspended.
      const tryResume = () => {
        if (audioCtx && audioCtx.state !== "running") {
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

  // Diagnostic table — exposed via window.__meetTrackInfo() so the Python
  // poller can see exactly which tracks were captured and whether they're
  // muted (no audio flowing).
  const trackInfo = [];
  window.__meetTrackInfo = () => trackInfo.map((t) => ({
    id: t.track.id,
    label: t.track.label,
    muted: t.track.muted,
    enabled: t.track.enabled,
    readyState: t.track.readyState,
    unmute_count: t.unmute_count,
    mute_count: t.mute_count,
  }));

  function pipeTrack(track) {
    if (!track || track.kind !== "audio") return;
    stats.audio_tracks_seen += 1;
    const entry = { track, unmute_count: 0, mute_count: 0 };
    trackInfo.push(entry);
    try {
      track.addEventListener("unmute", () => { entry.unmute_count += 1; });
      track.addEventListener("mute", () => { entry.mute_count += 1; });
    } catch (e) {}
    ensureAudioContext().then(async () => {
      if (workletReadyPromise) await workletReadyPromise;
      if (!audioCtx || !mixer) return;
      try {
        const ms = new MediaStream([track]);
        const src = audioCtx.createMediaStreamSource(ms);
        src.connect(mixer);
      } catch (e) {
        stats.last_error = "pipeTrack: " + String(e);
      }
    });
  }

  // ----- RTCPeerConnection wrap -----------------------------------------
  // Post-admission: existing PCs created during the join handshake have
  // already started ferrying audio; we won't catch their inbound tracks
  // here. The <audio> MutationObserver below picks up the bulk in practice.
  if (window.RTCPeerConnection && !window.RTCPeerConnection.__meetAudioWrapped) {
    const OrigPC = window.RTCPeerConnection;
    function WrappedPC() {
      const pc = new OrigPC(...arguments);
      stats.pcs_constructed += 1;
      try {
        pc.addEventListener("track", (ev) => {
          stats.tracks_attached += 1;
          pipeTrack(ev.track);
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
    Object.setPrototypeOf(WrappedPC, OrigPC);
    window.RTCPeerConnection = WrappedPC;
  }

  // ----- Pre-nav RTC capture pickup -------------------------------------
  // The pre-nav wrap installed via add_init_script (see meet_audio_source.py
  // _PRE_NAV_RTC_WRAP_JS) collects inbound audio tracks into
  // window.__meetCapturedTracks. We drain that array here and keep watching
  // it for additions (Meet may add tracks later as participants join/unmute).
  try {
    const captured = window.__meetCapturedTracks;
    if (Array.isArray(captured)) {
      captured.forEach((t) => pipeTrack(t));
      // Hot-patch push so future additions are immediately piped.
      const origPush = captured.push.bind(captured);
      captured.push = function () {
        for (const t of arguments) {
          try { pipeTrack(t); } catch (e) { stats.last_error = "pipe_push: " + String(e); }
        }
        return origPush.apply(captured, arguments);
      };
    }
  } catch (e) {
    stats.last_error = "captured_pickup: " + String(e);
  }

  // ----- HTMLMediaElement.srcObject setter patch ------------------------
  // The most reliable hook for catching audio that already exists at
  // post-admission injection time. Whenever Meet sets `el.srcObject = ...`
  // on an <audio> or <video>, we observe the assigned MediaStream and pipe
  // each audio track through our bridge.
  try {
    const proto = window.HTMLMediaElement && window.HTMLMediaElement.prototype;
    const desc = proto && Object.getOwnPropertyDescriptor(proto, "srcObject");
    if (desc && desc.set && !desc.set.__meetAudioWrapped) {
      const origSet = desc.set;
      const origGet = desc.get;
      function wrappedSet(stream) {
        origSet.call(this, stream);
        try {
          if (stream && typeof stream.getAudioTracks === "function") {
            stream.getAudioTracks().forEach((t) => pipeTrack(t));
            stream.addEventListener("addtrack", (e) => pipeTrack(e.track));
          }
        } catch (e) {
          stats.last_error = "srcObject_set: " + String(e);
        }
      }
      wrappedSet.__meetAudioWrapped = true;
      Object.defineProperty(proto, "srcObject", {
        set: wrappedSet,
        get: origGet,
        configurable: true,
        enumerable: true,
      });
    }
  } catch (e) {
    stats.last_error = "srcObject_patch: " + String(e);
  }

  // Also catch any existing <audio>/<video> that already had srcObject set
  // before our patch landed — walk them once now.
  try {
    Array.from(document.querySelectorAll("audio,video")).forEach((el) => {
      const s = el.srcObject;
      if (s && typeof s.getAudioTracks === "function") {
        s.getAudioTracks().forEach((t) => pipeTrack(t));
        s.addEventListener("addtrack", (e) => pipeTrack(e.track));
      }
    });
  } catch (e) {
    stats.last_error = "initial_scan: " + String(e);
  }

  // ----- <audio> MutationObserver fallback ------------------------------
  const adoptedAudio = new WeakSet();
  function adoptAudioEl(el) {
    if (adoptedAudio.has(el)) return;
    adoptedAudio.add(el);
    const tryAttach = () => {
      const stream = el.srcObject;
      if (stream && stream.getAudioTracks) {
        for (const t of stream.getAudioTracks()) pipeTrack(t);
      }
    };
    tryAttach();
    el.addEventListener("loadedmetadata", tryAttach);
  }
  try {
    const mo = new MutationObserver((muts) => {
      for (const m of muts) {
        for (const n of m.addedNodes || []) {
          if (n.nodeType !== 1) continue;
          if (n.tagName === "AUDIO") adoptAudioEl(n);
          if (n.querySelectorAll) {
            n.querySelectorAll("audio").forEach(adoptAudioEl);
          }
        }
      }
    });
    mo.observe(document.documentElement, { childList: true, subtree: true });
    if (document.querySelectorAll) {
      document.querySelectorAll("audio").forEach(adoptAudioEl);
    }
  } catch (e) {
    stats.last_error = "mutation_observer: " + String(e);
  }

  // ----- Speaker name DOM poll ------------------------------------------
  // Meet decorates the active speaker's tile/avatar with several different
  // attributes depending on the build; we cast a wide net and prefer the
  // most specific match. Output goes to window.meetSpeakerOnUpdate which
  // Python exposes; we de-dupe so Python sees one event per change.
  function readActiveSpeakerName() {
    // 1) An [data-self-name][data-allocation-index] tile with an active border.
    // 2) Any element with [data-talking="true"] (newer Meet builds).
    // 3) Fallback: largest non-self <video> tile's caption.
    const queries = [
      '[data-talking="true"][aria-label]',
      '[data-active-speaker="true"][aria-label]',
      '[data-is-speaking="true"][aria-label]',
    ];
    for (const q of queries) {
      const el = document.querySelector(q);
      if (el) {
        const label = (el.getAttribute("aria-label") || "").trim();
        if (label) return label.slice(0, 80);
      }
    }
    // Best-effort: look for the visible-speaker badge near a <video>.
    const tiles = document.querySelectorAll('[jsname][role="listitem"]');
    for (const t of tiles) {
      if (t.querySelector('[data-talking], [data-active-speaker]')) {
        const nameEl = t.querySelector('[data-self-name], [data-participant-name]');
        if (nameEl) return (nameEl.textContent || "").trim().slice(0, 80) || null;
      }
    }
    return null;
  }

  let lastSpeaker = null;
  const pollMs = Math.max(50, Math.floor(1000 / (cfg.speaker_poll_hz || 5)));
  setInterval(() => {
    try {
      const name = readActiveSpeakerName();
      if (name !== lastSpeaker) {
        lastSpeaker = name;
        stats.speaker_last = name;
        stats.speaker_updates += 1;
        if (typeof window.meetSpeakerOnUpdate === "function") {
          window.meetSpeakerOnUpdate(name || "");
        }
      }
    } catch (e) {
      stats.last_error = "speaker_poll: " + String(e);
    }
  }, pollMs);
})();
