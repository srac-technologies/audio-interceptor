/**
 * Electron Renderer - アプリケーションブートストラップ
 *
 * 共通コンポーネント + Electron アダプタを組み合わせてアプリを構成する。
 */

import { ApiClient } from '../shared/api/client.js';
import { setPlatformAdapter } from '../shared/platform.js';
import { createElectronAdapter } from './platform-electron.js';
import { TranscriptPanel } from '../shared/components/transcript-panel.js';
import { ResearchPanel } from '../shared/components/research-panel.js';
import { SettingsModal } from '../shared/components/settings-modal.js';
import { HistoryModal } from '../shared/components/history-modal.js';

// ---- プラットフォーム初期化 ----
const platform = createElectronAdapter();
setPlatformAdapter(platform);

document.body.classList.add('platform-electron');

// ---- API クライアント ----
const api = new ApiClient();

// ---- 状態 ----
let isRecording = false;
let micMuted = false;

// ---- DOM 参照 ----
const statusIndicator = document.getElementById('statusIndicator');
const statusText = document.getElementById('statusText');
const connectionDot = document.getElementById('connectionDot');
const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');
const stopBtnFloating = document.getElementById('stopBtnFloating');
const muteMicBtn = document.getElementById('muteMicBtn');
const transcribeCheckbox = document.getElementById('transcribeCheckbox');
const meetingTypeSelect = document.getElementById('meetingTypeSelect');
const meetingTitle = document.getElementById('meetingTitle');
const controlsDetails = document.getElementById('controlsDetails');
const fetchCalendarBtn = document.getElementById('fetchCalendarBtn');

// ---- 共通コンポーネント初期化 ----
const transcriptPanel = new TranscriptPanel(
  document.getElementById('transcriptArea'),
  { displayMode: 'bubble' }
);

const researchPanel = new ResearchPanel(
  document.getElementById('adviceArea')
);

const settingsModal = new SettingsModal(document.body, api);
settingsModal.onClose(() => loadMeetingTypes());

const historyModal = new HistoryModal(document.body, api);

// ---- WebSocket 接続 ----
api.on('connection', ({ connected }) => {
  if (connectionDot) {
    connectionDot.classList.toggle('connected', connected);
  }
  if (connected) {
    loadMeetingTypes();
    autoFetchCalendarTitle();
  }
});

api.on('transcript', (msg) => {
  transcriptPanel.addTranscript(msg.source, msg.text);
});

api.on('advice', (msg) => {
  researchPanel.addResearch(msg.trigger, msg.text, msg.timestamp);
});

api.on('status', (msg) => {
  if (msg.recording && !isRecording) {
    isRecording = true;
    updateRecordingUI(true);
  } else if (!msg.recording && isRecording) {
    isRecording = false;
    updateRecordingUI(false);
  }
});

api.on('mic_mute_status', (msg) => {
  micMuted = msg.muted;
  updateMuteButton();
});

api.connect();

// ---- 会議検知 (Electron固有) ----
platform.onPlatformEvent('meeting-detected', (data) => {
  console.log('Meeting detected:', data.app, data.title);
});

// ---- UI更新 ----
function updateRecordingUI(recording) {
  if (recording) {
    statusIndicator.classList.add('active');
    statusText.textContent = '録音中';
    startBtn.disabled = true;
    stopBtn.disabled = false;
    transcribeCheckbox.disabled = true;
    controlsDetails.open = false;
    muteMicBtn.style.display = 'block';
    stopBtnFloating.style.display = 'block';
    micMuted = false;
    updateMuteButton();
  } else {
    statusIndicator.classList.remove('active');
    statusText.textContent = '待機中';
    startBtn.disabled = false;
    stopBtn.disabled = true;
    transcribeCheckbox.disabled = false;
    controlsDetails.open = true;
    muteMicBtn.style.display = 'none';
    stopBtnFloating.style.display = 'none';
  }
}

function updateMuteButton() {
  if (micMuted) {
    muteMicBtn.textContent = 'マイクOFF';
    muteMicBtn.classList.add('muted');
  } else {
    muteMicBtn.textContent = 'マイクON';
    muteMicBtn.classList.remove('muted');
  }
}

// ---- 録音コントロール ----
async function handleStartRecording() {
  try {
    const options = {
      transcribeEnabled: transcribeCheckbox.checked,
      meetingTypeId: meetingTypeSelect.value ? parseInt(meetingTypeSelect.value) : null,
      title: meetingTitle.value || '無題の会議'
    };

    const result = await platform.startRecording(options);
    if (result.success) {
      transcriptPanel.clear();
      researchPanel.clear();
      isRecording = true;
      updateRecordingUI(true);
    } else {
      alert(`録音開始エラー: ${result.message}`);
    }
  } catch (error) {
    alert(`録音開始エラー: ${error.message}`);
  }
}

async function handleStopRecording() {
  try {
    const result = await platform.stopRecording();
    if (result.success) {
      isRecording = false;
      updateRecordingUI(false);
    } else {
      alert(`録音停止エラー: ${result.message}`);
    }
  } catch (error) {
    alert(`録音停止エラー: ${error.message}`);
  }
}

startBtn.addEventListener('click', handleStartRecording);
stopBtn.addEventListener('click', handleStopRecording);
stopBtnFloating.addEventListener('click', handleStopRecording);

muteMicBtn.addEventListener('click', async () => {
  try {
    const result = await api.toggleMicMute(!micMuted);
    if (result.success) {
      micMuted = !micMuted;
      updateMuteButton();
    }
  } catch (error) {
    console.error('Failed to toggle mic mute:', error);
  }
});

// ---- 会議種別 ----
async function loadMeetingTypes() {
  try {
    const data = await api.getMeetingTypes();
    meetingTypeSelect.innerHTML = '<option value="">選択してください</option>';
    data.meeting_types.forEach(type => {
      const option = document.createElement('option');
      option.value = type.id;
      option.textContent = type.name;
      meetingTypeSelect.appendChild(option);
    });
  } catch (error) {
    console.error('Failed to load meeting types:', error);
    setTimeout(loadMeetingTypes, 5000);
  }
}

// ---- カレンダー連携 ----
async function autoFetchCalendarTitle() {
  if (meetingTitle.value) return;
  try {
    const data = await api.getCurrentCalendarEvent();
    if (data.success && data.event && !meetingTitle.value) {
      meetingTitle.value = data.event.summary;
      meetingTitle.style.borderColor = 'var(--color-accent)';
      setTimeout(() => { meetingTitle.style.borderColor = ''; }, 2000);
    }
  } catch (error) {
    console.error('Auto-fetch calendar failed:', error);
  }
}

fetchCalendarBtn.addEventListener('click', async () => {
  const originalText = fetchCalendarBtn.textContent;
  try {
    fetchCalendarBtn.textContent = '取得中...';
    fetchCalendarBtn.disabled = true;
    const data = await api.getCurrentCalendarEvent();
    if (data.success && data.event) {
      meetingTitle.value = data.event.summary;
      fetchCalendarBtn.textContent = '取得完了';
      setTimeout(() => { fetchCalendarBtn.textContent = originalText; }, 2000);
    } else {
      alert('現在時刻付近にカレンダーイベントが見つかりませんでした');
      fetchCalendarBtn.textContent = originalText;
    }
  } catch (error) {
    alert('カレンダー取得に失敗しました');
    fetchCalendarBtn.textContent = originalText;
  } finally {
    fetchCalendarBtn.disabled = false;
  }
});

// ---- モーダル ----
document.getElementById('historyBtn').addEventListener('click', () => historyModal.open());
document.getElementById('settingsBtn').addEventListener('click', () => settingsModal.open());
