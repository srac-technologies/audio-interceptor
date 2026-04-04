/**
 * Electron プラットフォームアダプタ
 *
 * Electron 固有の機能（IPC, 通知, ドラッグ, ファイルシステム）をラップし、
 * 共通の PlatformAdapter インターフェースを提供する。
 */

const { ipcRenderer } = require('electron');

export function createElectronAdapter() {
  const eventHandlers = {};

  // Electron → Renderer のイベント受信
  ipcRenderer.on('meeting-detected', (_event, data) => {
    const handlers = eventHandlers['meeting-detected'];
    if (handlers) handlers.forEach(h => h(data));
  });

  return {
    type: 'electron',

    async startRecording(options) {
      return ipcRenderer.invoke('start-recording', {
        transcribe_enabled: options.transcribeEnabled ?? false,
        meeting_type_id: options.meetingTypeId ?? null,
        title: options.title || '無題の会議'
      });
    },

    async stopRecording() {
      return ipcRenderer.invoke('stop-recording');
    },

    showNotification(title, body) {
      // Electron main process 側で Notification を表示するため、
      // renderer からは window.Notification を使う
      if ('Notification' in window && Notification.permission === 'granted') {
        new Notification(title, { body });
      }
    },

    supportsDrag() {
      return true;
    },

    supportsFileSystem() {
      return true;
    },

    onPlatformEvent(event, handler) {
      if (!eventHandlers[event]) eventHandlers[event] = [];
      eventHandlers[event].push(handler);
    }
  };
}
