// --- 設定 ---
const WS_URL = 'ws://localhost:8000/ws';
const API_BASE = 'http://localhost:8000';
const RECONNECT_INTERVAL = 3000;
const PING_INTERVAL = 15000;

// --- 状態 ---
let ws = null;
let recording = false;
let micMuted = false;
let transcriptCount = 0;
let researchCount = 0;
let pingTimer = null;

// --- DOM ---
const $ = (sel) => document.querySelector(sel);
const connectionDot = $('#connection-dot');
const btnStart = $('#btn-start');
const btnStop = $('#btn-stop');
const btnMute = $('#btn-mute');
const meetingTitle = $('#meeting-title');
const panelTranscript = $('#panel-transcript');
const panelResearch = $('#panel-research');
const transcriptBadge = $('#transcript-count');
const researchBadge = $('#research-count');
const recordingIndicator = $('#recording-indicator');
const statusText = $('#status-text');

// --- WebSocket ---
function connect() {
  if (ws && ws.readyState <= WebSocket.OPEN) return;

  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    setConnected(true);
    statusText.textContent = '接続済み';
    startPing();
  };

  ws.onclose = () => {
    setConnected(false);
    stopPing();
    statusText.textContent = '切断 — 再接続中...';
    setTimeout(connect, RECONNECT_INTERVAL);
  };

  ws.onerror = () => {
    ws.close();
  };

  ws.onmessage = (event) => {
    if (event.data === 'pong') return;
    try {
      const msg = JSON.parse(event.data);
      handleMessage(msg);
    } catch (e) {
      // ignore non-JSON
    }
  };
}

function startPing() {
  stopPing();
  pingTimer = setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send('ping');
    }
  }, PING_INTERVAL);
}

function stopPing() {
  if (pingTimer) {
    clearInterval(pingTimer);
    pingTimer = null;
  }
}

function setConnected(connected) {
  connectionDot.classList.toggle('connected', connected);
  connectionDot.title = connected ? '接続中' : '未接続';
}

// --- メッセージハンドラ ---
function handleMessage(msg) {
  switch (msg.type) {
    case 'status':
      handleStatus(msg);
      break;
    case 'transcript':
      addTranscript(msg.source, msg.text);
      break;
    case 'advice':
      addResearch(msg.trigger, msg.text, msg.timestamp);
      break;
    case 'mic_mute_status':
      micMuted = msg.muted;
      updateMuteButton();
      break;
  }
}

function handleStatus(msg) {
  recording = msg.recording;
  updateRecordingUI();

  if (msg.status === 'recording_started') {
    statusText.textContent = '録音中...';
  } else if (msg.status === 'recording_stopped') {
    statusText.textContent = '録音停止';
  }
}

// --- 文字起こし表示 ---
function addTranscript(source, text) {
  clearEmptyState(panelTranscript);

  const entry = document.createElement('div');
  entry.className = 'transcript-entry';
  entry.innerHTML = `<span class="source">[${escapeHtml(source)}]</span> <span class="text">${escapeHtml(text)}</span>`;
  panelTranscript.appendChild(entry);

  transcriptCount++;
  transcriptBadge.textContent = transcriptCount;

  // 自動スクロール
  panelTranscript.scrollTop = panelTranscript.scrollHeight;
}

// --- リサーチ表示 ---
function addResearch(trigger, text, timestamp) {
  clearEmptyState(panelResearch);

  const entry = document.createElement('div');
  entry.className = 'research-entry';

  const timeStr = timestamp ? new Date(timestamp).toLocaleTimeString('ja-JP') : '';
  entry.innerHTML = `
    <div class="trigger">${escapeHtml(trigger)}</div>
    <div class="content">${escapeHtml(text)}</div>
    ${timeStr ? `<div class="time">${timeStr}</div>` : ''}
  `;
  panelResearch.appendChild(entry);

  researchCount++;
  researchBadge.textContent = researchCount;

  panelResearch.scrollTop = panelResearch.scrollHeight;
}

function clearEmptyState(panel) {
  const empty = panel.querySelector('.empty-state');
  if (empty) empty.remove();
}

// --- 録音コントロール ---
async function startRecording() {
  try {
    const res = await fetch(`${API_BASE}/recording/start`, { method: 'POST' });
    if (!res.ok) throw new Error(await res.text());
  } catch (e) {
    statusText.textContent = `エラー: ${e.message}`;
  }
}

async function stopRecording() {
  try {
    const res = await fetch(`${API_BASE}/recording/stop`, { method: 'POST' });
    if (!res.ok) throw new Error(await res.text());
  } catch (e) {
    statusText.textContent = `エラー: ${e.message}`;
  }
}

async function toggleMute() {
  try {
    const res = await fetch(`${API_BASE}/recording/mute-mic`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ muted: !micMuted })
    });
    if (!res.ok) throw new Error(await res.text());
  } catch (e) {
    statusText.textContent = `エラー: ${e.message}`;
  }
}

// --- 会議タイトル更新 ---
let titleDebounce = null;
function onTitleChange() {
  clearTimeout(titleDebounce);
  titleDebounce = setTimeout(async () => {
    if (!recording) return;
    try {
      await fetch(`${API_BASE}/recording`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: meetingTitle.value })
      });
    } catch (e) {
      // タイトル更新失敗は無視
    }
  }, 500);
}

// --- UI更新 ---
function updateRecordingUI() {
  btnStart.disabled = recording;
  btnStop.disabled = !recording;
  btnMute.disabled = !recording;
  recordingIndicator.classList.toggle('active', recording);

  if (!recording) {
    micMuted = false;
    updateMuteButton();
  }
}

function updateMuteButton() {
  btnMute.textContent = micMuted ? '🔇' : '🎤';
  btnMute.classList.toggle('muted', micMuted);
  btnMute.title = micMuted ? 'ミュート解除' : 'マイクミュート';
}

// --- タブ切り替え ---
function initTabs() {
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
      tab.classList.add('active');

      const target = tab.dataset.tab;
      panelTranscript.hidden = target !== 'transcript';
      panelResearch.hidden = target !== 'research';
    });
  });
}

// --- ユーティリティ ---
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// --- 初期化 ---
function init() {
  initTabs();
  updateRecordingUI();

  btnStart.addEventListener('click', startRecording);
  btnStop.addEventListener('click', stopRecording);
  btnMute.addEventListener('click', toggleMute);
  meetingTitle.addEventListener('input', onTitleChange);

  connect();
}

init();
