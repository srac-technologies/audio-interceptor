// bot_server viewer client.
//
// Connects to /v/{slug}/ws. Receives:
//   {type:"transcript", text, speaker, ts}     → append to overlay list
//   {type:"snapshot",   view_mode, view_type, content, stats, ...}
//                                              → replace stage SVG / HTML / Mermaid
//   {type:"viewer_error", detail}              → status chip → ERR
//   {type:"status", ...}                       → ignored (bot lifecycle)
// Sends:
//   {type:"set_view", mode}                    → server changes mode + re-renders
//   {type:"set_enabled", enabled}              → toggle graphic recording
//
// Token: read from query string ?token= if present, else not sent.

(() => {
  const slug = document.body.dataset.slug;
  const stage = document.getElementById("stage");
  const statusEl = document.getElementById("status");
  const metaEl = document.getElementById("meta");
  const enabledEl = document.getElementById("enabled");
  const tabs = document.querySelectorAll("#tabs .tab");
  const transcriptList = document.getElementById("transcript-list");
  const transcriptCount = document.getElementById("transcript-count");
  const transcriptToggle = document.getElementById("transcript-toggle");
  const transcriptArrow = document.getElementById("transcript-arrow");
  const overlay = document.getElementById("transcript-overlay");

  const seen = { mindmap: new Set(), tree: new Set(), kanban: new Set() };
  let currentMode = "mindmap";
  let mermaidReady = false;
  let mermaidLoadingPromise = null;
  let mermaidCounter = 0;
  let ws = null;
  let reconnectTimer = null;
  let backoffMs = 1000;
  const MAX_BACKOFF = 15000;

  function setStatus(text, cls) {
    statusEl.textContent = text;
    statusEl.className = "chip " + (cls || "");
  }

  function setActiveTab(mode) {
    tabs.forEach(t => t.classList.toggle("active", t.dataset.mode === mode));
    document.body.classList.toggle("transcript-mode", mode === "transcript");
  }

  function loadMermaid() {
    if (mermaidReady) return Promise.resolve();
    if (mermaidLoadingPromise) return mermaidLoadingPromise;
    mermaidLoadingPromise = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js";
      s.onload = () => {
        window.mermaid.initialize({
          startOnLoad: false, theme: "default", securityLevel: "loose",
          mindmap: { padding: 16 },
        });
        mermaidReady = true;
        resolve();
      };
      s.onerror = (e) => reject(e);
      document.head.appendChild(s);
    });
    return mermaidLoadingPromise;
  }

  async function renderMermaid(dsl) {
    await loadMermaid();
    mermaidCounter += 1;
    const id = "mmd-" + mermaidCounter;
    try {
      const { svg } = await window.mermaid.render(id, dsl);
      stage.innerHTML = '<div class="mermaid">' + svg + '</div>';
    } catch (e) {
      stage.innerHTML = '<div class="empty">Mermaid描画エラー: ' + e.message + '</div>';
    }
  }

  function applySvg(svgText, modeKey, animateNew) {
    stage.innerHTML = svgText;
    if (!seen[modeKey]) return;
    if (!animateNew) {
      stage.querySelectorAll('#nodes > g.node').forEach(el => seen[modeKey].add(el.id));
      return;
    }
    stage.querySelectorAll('#nodes > g.node').forEach(el => {
      if (!seen[modeKey].has(el.id)) {
        el.classList.add('node-new');
        seen[modeKey].add(el.id);
      }
    });
  }

  function applySnapshot(msg, animateNew) {
    const mode = msg.view_mode || currentMode;
    currentMode = mode;
    setActiveTab(mode);
    if (msg.view_type === "svg") {
      applySvg(msg.content, mode, animateNew);
    } else if (msg.view_type === "mermaid") {
      renderMermaid(msg.content);
    } else if (msg.view_type === "html") {
      stage.innerHTML = msg.content;
    }
    if (msg.stats) {
      metaEl.textContent =
        `nodes=${msg.node_count}  +${msg.stats.nodes_new || 0}n/+${msg.stats.edges_new || 0}e  ` +
        `lat=${(msg.latency || 0).toFixed(1)}s  「${(msg.chunk || '').slice(0, 30)}」`;
    } else {
      metaEl.textContent = `nodes=${msg.node_count} edges=${msg.edge_count}`;
    }
    if (typeof msg.enabled === "boolean") {
      enabledEl.checked = msg.enabled;
    }
  }

  function appendTranscript(msg) {
    const entry = document.createElement("div");
    entry.className = "entry";
    const speaker = msg.speaker
      ? `<span class="speaker">${escapeHtml(msg.speaker)}</span>`
      : "";
    const ts = msg.ts
      ? `<span class="ts">${shortTs(msg.ts)}</span>`
      : "";
    entry.innerHTML = `${ts}${speaker}<span>${escapeHtml(msg.text || "")}</span>`;
    transcriptList.appendChild(entry);
    // Trim — keep DOM small.
    while (transcriptList.children.length > 200) {
      transcriptList.removeChild(transcriptList.firstChild);
    }
    transcriptCount.textContent = transcriptList.children.length + " 件";
    transcriptList.scrollTop = transcriptList.scrollHeight;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
    })[c]);
  }

  function shortTs(iso) {
    try {
      const d = new Date(iso);
      return d.toLocaleTimeString("ja-JP", { hour12: false });
    } catch (e) {
      return "";
    }
  }

  function connect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token");
    const wsProto = location.protocol === "https:" ? "wss" : "ws";
    const url = `${wsProto}://${location.host}/v/${encodeURIComponent(slug)}/ws`
      + (token ? `?token=${encodeURIComponent(token)}` : "");
    setStatus("接続中…");
    ws = new WebSocket(url);
    ws.addEventListener("open", () => {
      setStatus("接続済", "ok");
      backoffMs = 1000;
    });
    ws.addEventListener("message", (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      const t = msg.type;
      if (t === "snapshot") {
        applySnapshot(msg, true);
      } else if (t === "transcript") {
        appendTranscript(msg);
      } else if (t === "viewer_error") {
        setStatus("LLM ERR: " + (msg.detail || "").slice(0, 60), "err");
      } else if (t === "status") {
        // Bot-side lifecycle. Show a soft hint.
        if (msg.state === "left") {
          setStatus("bot 離脱", "warn");
        } else if (msg.state === "joined") {
          setStatus("接続済 / bot in", "ok");
        }
      }
    });
    ws.addEventListener("close", (ev) => {
      setStatus(`切断 (${ev.code}) — 再接続`, "warn");
      scheduleReconnect();
    });
    ws.addEventListener("error", () => {
      // close will fire right after; no need to handle separately.
    });
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, backoffMs);
    backoffMs = Math.min(backoffMs * 2, MAX_BACKOFF);
  }

  function sendControl(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(obj));
    }
  }

  tabs.forEach(t => {
    t.addEventListener("click", () => {
      const mode = t.dataset.mode;
      if (mode === currentMode) return;
      setActiveTab(mode);
      sendControl({ type: "set_view", mode });
    });
  });

  enabledEl.addEventListener("change", () => {
    sendControl({ type: "set_enabled", enabled: enabledEl.checked });
  });

  transcriptToggle.addEventListener("click", () => {
    overlay.classList.toggle("collapsed");
    transcriptArrow.textContent = overlay.classList.contains("collapsed") ? "▴" : "▾";
  });

  connect();
})();
