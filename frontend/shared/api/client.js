/**
 * ApiClient - バックエンド通信の共通レイヤー
 *
 * HTTP REST + WebSocket を1つのクラスにまとめ、
 * Electron / Chrome Extension 双方が同じ API で通信できるようにする。
 */

const DEFAULT_WS_URL = 'ws://localhost:8000/ws';
const DEFAULT_API_BASE = 'http://localhost:8000';
const RECONNECT_INTERVAL = 3000;

export class ApiClient {
  /**
   * @param {Object} [options]
   * @param {string} [options.apiBase]
   * @param {string} [options.wsUrl]
   */
  constructor(options = {}) {
    this.apiBase = options.apiBase || DEFAULT_API_BASE;
    this.wsUrl = options.wsUrl || DEFAULT_WS_URL;
    this._ws = null;
    this._listeners = {};
    this._connected = false;
  }

  // ---- WebSocket ----

  connect() {
    if (this._ws && this._ws.readyState <= WebSocket.OPEN) return;

    this._ws = new WebSocket(this.wsUrl);

    this._ws.onopen = () => {
      this._connected = true;
      this._emit('connection', { connected: true });
    };

    this._ws.onclose = () => {
      this._connected = false;
      this._emit('connection', { connected: false });
      setTimeout(() => this.connect(), RECONNECT_INTERVAL);
    };

    this._ws.onerror = () => {
      this._ws.close();
    };

    this._ws.onmessage = (event) => {
      if (event.data === 'pong') return;
      try {
        const msg = JSON.parse(event.data);
        this._emit('message', msg);
        // メッセージタイプ別にも emit
        if (msg.type) {
          this._emit(msg.type, msg);
        }
      } catch (e) {
        // non-JSON は無視
      }
    };
  }

  disconnect() {
    if (this._ws) {
      this._ws.onclose = null; // 再接続を防止
      this._ws.close();
      this._ws = null;
      this._connected = false;
    }
  }

  get connected() {
    return this._connected;
  }

  // ---- HTTP API ----

  async startRecording(options = {}) {
    return this._post('/recording/start', {
      transcribe_enabled: options.transcribeEnabled ?? false,
      meeting_type_id: options.meetingTypeId ?? null,
      title: options.title || '無題の会議',
      tmp_dir: './tmp'
    });
  }

  async stopRecording() {
    return this._post('/recording/stop');
  }

  async toggleMicMute(muted) {
    return this._post('/recording/mute-mic', { muted });
  }

  async updateRecordingTitle(title) {
    return this._fetch('/recording', {
      method: 'PATCH',
      body: { title }
    });
  }

  async getMeetingTypes() {
    return this._get('/meeting-types');
  }

  async createMeetingType(name) {
    return this._post('/meeting-types', { name });
  }

  async deleteMeetingType(id) {
    return this._delete(`/meeting-types/${id}`);
  }

  async getPrompts(meetingTypeId) {
    return this._get(`/meeting-types/${meetingTypeId}/prompts`);
  }

  async createPrompt(meetingTypeId, triggerCondition, actionPrompt) {
    return this._post('/prompts', {
      meeting_type_id: meetingTypeId,
      trigger_condition: triggerCondition,
      action_prompt: actionPrompt
    });
  }

  async deletePrompt(id) {
    return this._delete(`/prompts/${id}`);
  }

  async getCurrentCalendarEvent() {
    return this._get('/calendar/current');
  }

  async getHistory() {
    return this._get('/history');
  }

  async getHistoryDetail(sessionId) {
    return this._get(`/history/${sessionId}`);
  }

  async updateSessionTitle(sessionId, title) {
    return this._fetch(`/history/${sessionId}`, {
      method: 'PATCH',
      body: { title }
    });
  }

  getDocxDownloadUrl(sessionId) {
    return `${this.apiBase}/history/${sessionId}/download/docx`;
  }

  async getSettings() {
    return this._get('/settings');
  }

  async saveSettings(settings) {
    return this._post('/settings', { settings });
  }

  async getPlugins() {
    return this._get('/plugins');
  }

  async createPlugin(plugin) {
    return this._post('/plugins', plugin);
  }

  async updatePlugin(name, data) {
    return this._fetch(`/plugins/${encodeURIComponent(name)}`, {
      method: 'PUT',
      body: data
    });
  }

  async deletePlugin(name) {
    return this._delete(`/plugins/${encodeURIComponent(name)}`);
  }

  // ---- イベント ----

  on(event, handler) {
    if (!this._listeners[event]) this._listeners[event] = [];
    this._listeners[event].push(handler);
    return () => this.off(event, handler);
  }

  off(event, handler) {
    const handlers = this._listeners[event];
    if (handlers) {
      this._listeners[event] = handlers.filter(h => h !== handler);
    }
  }

  _emit(event, data) {
    const handlers = this._listeners[event];
    if (handlers) {
      handlers.forEach(h => h(data));
    }
  }

  // ---- 内部ヘルパー ----

  async _get(path) {
    const res = await fetch(`${this.apiBase}${path}`);
    return res.json();
  }

  async _post(path, body) {
    const res = await fetch(`${this.apiBase}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined
    });
    return res.json();
  }

  async _delete(path) {
    const res = await fetch(`${this.apiBase}${path}`, { method: 'DELETE' });
    return res.json();
  }

  async _fetch(path, { method, body } = {}) {
    const res = await fetch(`${this.apiBase}${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined
    });
    return res.json();
  }
}
