/**
 * Chrome Extension プラットフォームアダプタ
 *
 * Chrome Extension 固有の制約に合わせた実装。
 * 録音開始/停止は HTTP API を直接呼ぶ（IPC 不要）。
 */

const API_BASE = 'http://localhost:8000';

export function createChromeAdapter() {
  return {
    type: 'chrome-extension',

    async startRecording(options) {
      const res = await fetch(`${API_BASE}/recording/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          transcribe_enabled: options.transcribeEnabled ?? false,
          meeting_type_id: options.meetingTypeId ?? null,
          title: options.title || '無題の会議',
          tmp_dir: './tmp'
        })
      });
      return res.json();
    },

    async stopRecording() {
      const res = await fetch(`${API_BASE}/recording/stop`, { method: 'POST' });
      return res.json();
    },

    showNotification(title, body) {
      // Chrome Extension では chrome.notifications API を使うが、
      // sidePanel からは直接使えないため service worker 経由が必要。
      // 簡易実装として console.log にフォールバック。
      console.log(`[Notification] ${title}: ${body}`);
    },

    supportsDrag() {
      return false;
    },

    supportsFileSystem() {
      return false;
    },

    onPlatformEvent(_event, _handler) {
      // Chrome Extension では会議検知などのプラットフォームイベントは不要
    }
  };
}
