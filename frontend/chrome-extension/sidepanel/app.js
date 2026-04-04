/**
 * Chrome Extension SidePanel - アプリケーションブートストラップ
 *
 * 共通コンポーネント + Chrome アダプタを組み合わせ、
 * サイドパネル向けのコンパクトUIを構成する。
 */

import { ApiClient } from '../../shared/api/client.js';
import { setPlatformAdapter } from '../../shared/platform.js';
import { createChromeAdapter } from './platform-chrome.js';
import { TranscriptPanel } from '../../shared/components/transcript-panel.js';
import { ResearchPanel } from '../../shared/components/research-panel.js';

// ---- プラットフォーム初期化 ----
const platform = createChromeAdapter();
setPlatformAdapter(platform);

// ---- API クライアント ----
const api = new ApiClient();

// ---- 状態 ----
let recording = false;
let micMuted = false;
let transcriptCount = 0;
let researchCount = 0;

// ---- DOM 参照 ----
const connectionDot = document.getElementById('connection-dot');
const btnStart = document.getElementById('btn-start');
const btnStop = document.getElementById('btn-stop');
const btnMute = document.getElementById('btn-mute');
const meetingTitleInput = document.getElementById('meeting-title');
const panelTranscript = document.getElementById('panel-transcript');
const panelResearch = document.getElementById('panel-research');
const transcriptBadge = document.getElementById('transcript-count');
const researchBadge = document.getElementById('research-count');
const recordingIndicator = document.getElementById('recording-indicator');
const statusText = document.getElementById('status-text');

// ---- 共通コンポーネント初期化 ----
const transcriptPanel = new TranscriptPanel(panelTranscript, { displayMode: 'compact' });
const researchPanel = new ResearchPanel(panelResearch);

transcriptPanel.onCountChange((count) => {
  transcriptBadge.textContent = count;
});

researchPanel.onCountChange((count) => {
  researchBadge.textContent = count;
});

// ---- WebSocket 接続 ----
api.on('connection', ({ connected }) => {
  connectionDot.classList.toggle('connected', connected);
  connectionDot.title = connected ? '接続中' : '未接続';
  statusText.textContent = connected ? '接続済み' : '切断 — 再接続中...';
});

api.on('transcript', (msg) => {
  transcriptPanel.addTranscript(msg.source, msg.text);
});

api.on('advice', (msg) => {
  researchPanel.addResearch(msg.trigger, msg.text, msg.timestamp);
});

api.on('status', (msg) => {
  recording = msg.recording;
  updateRecordingUI();

  if (msg.status === 'recording_started') {
    statusText.textContent = '録音中...';
  } else if (msg.status === 'recording_stopped') {
    statusText.textContent = '録音停止';
  }
});

api.on('mic_mute_status', (msg) => {
  micMuted = msg.muted;
  updateMuteButton();
});

api.connect();

// ---- UI更新 ----
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

// ---- 録音コントロール ----
btnStart.addEventListener('click', async () => {
  try {
    const result = await platform.startRecording({
      title: meetingTitleInput.value || '無題の会議'
    });
    if (result.success) {
      transcriptPanel.clear();
      researchPanel.clear();
    }
  } catch (e) {
    statusText.textContent = `エラー: ${e.message}`;
  }
});

btnStop.addEventListener('click', async () => {
  try {
    await platform.stopRecording();
  } catch (e) {
    statusText.textContent = `エラー: ${e.message}`;
  }
});

btnMute.addEventListener('click', async () => {
  try {
    await api.toggleMicMute(!micMuted);
  } catch (e) {
    statusText.textContent = `エラー: ${e.message}`;
  }
});

// ---- タブ切り替え ----
document.querySelectorAll('.ma-tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.ma-tab').forEach((t) => t.classList.remove('active'));
    tab.classList.add('active');

    const target = tab.dataset.tab;
    panelTranscript.hidden = target !== 'transcript';
    panelResearch.hidden = target !== 'research';
  });
});

// ---- 会議タイトル更新 ----
let titleDebounce = null;
meetingTitleInput.addEventListener('input', () => {
  clearTimeout(titleDebounce);
  titleDebounce = setTimeout(async () => {
    if (!recording) return;
    try {
      await api.updateRecordingTitle(meetingTitleInput.value);
    } catch (e) {
      // タイトル更新失敗は無視
    }
  }, 500);
});

// ---- 初期化 ----
updateRecordingUI();
