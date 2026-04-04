/**
 * SettingsModal - 設定画面コンポーネント
 *
 * 一般設定 / 会議種別・プロンプト / プラグイン の3タブ構成。
 * モーダル表示は Electron でのみ使用。Chrome Extension では別途画面を検討。
 */
export class SettingsModal {
  /**
   * @param {HTMLElement} container - モーダルを挿入するコンテナ
   * @param {import('../api/client.js').ApiClient} apiClient
   */
  constructor(container, apiClient) {
    this.container = container;
    this.api = apiClient;
    this.selectedTypeId = null;
    this._render();
    this._bindEvents();
  }

  open() {
    this.el.classList.add('open');
    this._loadSettings();
    this._renderMeetingTypes();
  }

  close() {
    this.el.classList.remove('open');
    this._onClose?.();
  }

  onClose(handler) {
    this._onClose = handler;
  }

  _render() {
    this.el = document.createElement('div');
    this.el.className = 'ma-modal';
    this.el.innerHTML = `
      <div class="ma-modal-content">
        <div class="ma-modal-header">
          <h2>設定</h2>
          <button class="ma-close-btn" data-action="close">&times;</button>
        </div>

        <div class="ma-modal-tabs">
          <button class="ma-modal-tab active" data-tab="general">一般設定</button>
          <button class="ma-modal-tab" data-tab="meeting-types">会議種別・プロンプト</button>
          <button class="ma-modal-tab" data-tab="plugins">プラグイン</button>
        </div>

        <!-- 一般設定 -->
        <div class="ma-modal-tab-content active" data-tab-content="general">
          <div class="ma-form-group">
            <label class="ma-checkbox-group">
              <input type="checkbox" data-setting="auto_summary_enabled">
              <span>会議終了時にサマリーを自動生成＆保存する</span>
            </label>
          </div>
          <div class="ma-form-group">
            <label>保存先ディレクトリ</label>
            <input type="text" class="ma-input" data-setting="save_dir" placeholder="/home/user/Documents/MeetingLogs">
          </div>
          <div class="ma-form-group">
            <label>Google Calendar ID</label>
            <input type="text" class="ma-input" data-setting="calendar_id" placeholder="primary">
            <div class="ma-hint">※ サービスアカウント使用時は共有されたカレンダーIDを指定</div>
          </div>
          <div class="ma-form-group">
            <label>サマリー生成用プロンプト</label>
            <textarea class="ma-textarea" data-setting="summary_prompt" style="height: 150px;"></textarea>
          </div>

          <hr class="ma-divider">
          <h3 class="ma-section-title">リサーチ機能</h3>

          <div class="ma-form-group">
            <label class="ma-checkbox-group">
              <input type="checkbox" data-setting="research_enabled">
              <span>リサーチ機能を有効化</span>
            </label>
          </div>
          <div class="ma-form-group">
            <label>リサーチ方式</label>
            <select class="ma-select" data-setting="research_method">
              <option value="llm">LLMのみ（高速）</option>
              <option value="hybrid">ハイブリッド（全ソース並列実行）</option>
            </select>
          </div>
          <div class="ma-form-group">
            <label>リサーチバッファサイズ</label>
            <input type="number" class="ma-input" data-setting="research_buffer_size" min="1" max="20" placeholder="2">
          </div>
          <div class="ma-form-group">
            <label>リサーチ対象</label>
            <select class="ma-select" data-setting="research_target_sources">
              <option value="speaker">スピーカーのみ</option>
              <option value="mic">マイクのみ</option>
              <option value="both">両方</option>
            </select>
          </div>
          <div class="ma-form-group">
            <label class="ma-checkbox-group">
              <input type="checkbox" data-setting="research_transcription_refinement">
              <span>文字起こし精度向上（NER前にLLMで修正）</span>
            </label>
          </div>
          <div class="ma-form-group">
            <label>NER（固有名詞抽出）プロンプト</label>
            <textarea class="ma-textarea" data-setting="ner_prompt" style="height: 100px;" placeholder="会話から固有名詞を抽出..."></textarea>
          </div>

          <h4 style="margin: 15px 0 10px; color: var(--color-mic);">Slack統合（オプション）</h4>
          <div class="ma-form-group">
            <label>Slack Bot Token</label>
            <input type="password" class="ma-input" data-setting="slack_bot_token" placeholder="xoxb-...">
          </div>
          <div class="ma-form-group">
            <label>Slack チャンネル</label>
            <input type="text" class="ma-input" data-setting="slack_channel" placeholder="#meeting-research">
          </div>

          <div class="ma-text-right" style="margin-top: 20px;">
            <button class="ma-btn ma-btn-save" data-action="save-settings">設定を保存</button>
          </div>
          <div class="ma-hint ma-text-right" style="margin-top: 10px;">
            リサーチ機能の設定は録音中でもリアルタイムで反映されます
          </div>
        </div>

        <!-- 会議種別タブ -->
        <div class="ma-modal-tab-content" data-tab-content="meeting-types">
          <div style="display: flex; flex: 1; gap: 20px; min-height: 0;">
            <div style="flex: 1; display: flex; flex-direction: column;">
              <h3>会議種別</h3>
              <div data-ref="meetingTypeList" style="flex: 1; overflow-y: auto; margin-bottom: 10px;"></div>
              <div style="display: flex; gap: 5px;">
                <input type="text" class="ma-input" data-ref="newTypeName" placeholder="種別名">
                <button class="ma-btn" data-action="add-type" style="width: auto;">追加</button>
              </div>
            </div>
            <div style="flex: 2; display: flex; flex-direction: column;">
              <h3 data-ref="promptsHeader">プロンプト</h3>
              <div data-ref="promptsList" style="flex: 1; overflow-y: auto; margin-bottom: 10px;"></div>
              <div data-ref="promptForm" style="display: none; flex-direction: column; gap: 10px;">
                <input type="text" class="ma-input" data-ref="newTrigger" placeholder="トリガー条件">
                <textarea class="ma-textarea" data-ref="newAction" placeholder="AIへの指示" style="height: 60px;"></textarea>
                <button class="ma-btn" data-action="add-prompt">追加</button>
              </div>
            </div>
          </div>
        </div>

        <!-- プラグインタブ -->
        <div class="ma-modal-tab-content" data-tab-content="plugins">
          <div style="margin-bottom: 15px;">
            <p class="ma-hint">外部プログラムがMeeting Assistantのイベントを購読できます。</p>
          </div>
          <div data-ref="pluginList" style="flex: 1; overflow-y: auto; margin-bottom: 15px;"></div>
          <hr class="ma-divider">
          <h4 class="ma-section-title">プラグイン追加</h4>
          <div class="ma-form-group">
            <label>名前</label>
            <input type="text" class="ma-input" data-ref="pluginName" placeholder="my-plugin">
          </div>
          <div class="ma-form-group">
            <label>プロトコル</label>
            <select class="ma-select" data-ref="pluginProtocol">
              <option value="websocket">WebSocket</option>
              <option value="webhook">HTTP Webhook</option>
              <option value="pipe">Shell Pipe</option>
              <option value="exec">プロセス起動</option>
            </select>
          </div>
          <div class="ma-form-group">
            <label>エンドポイント / コマンド</label>
            <input type="text" class="ma-input" data-ref="pluginEndpoint" placeholder="http://localhost:9999/webhook">
          </div>
          <div class="ma-form-group">
            <label>購読イベント（空欄で全イベント）</label>
            <div data-ref="pluginEvents" style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 5px;">
              <label class="ma-checkbox-group" style="flex: 0 0 auto;"><input type="checkbox" value="transcription"><span>transcription</span></label>
              <label class="ma-checkbox-group" style="flex: 0 0 auto;"><input type="checkbox" value="research_result"><span>research_result</span></label>
              <label class="ma-checkbox-group" style="flex: 0 0 auto;"><input type="checkbox" value="session_start"><span>session_start</span></label>
              <label class="ma-checkbox-group" style="flex: 0 0 auto;"><input type="checkbox" value="session_end"><span>session_end</span></label>
              <label class="ma-checkbox-group" style="flex: 0 0 auto;"><input type="checkbox" value="meeting_detected"><span>meeting_detected</span></label>
              <label class="ma-checkbox-group" style="flex: 0 0 auto;"><input type="checkbox" value="summary_generated"><span>summary_generated</span></label>
            </div>
          </div>
          <div class="ma-text-right">
            <button class="ma-btn ma-btn-save" data-action="add-plugin">追加</button>
          </div>
        </div>
      </div>
    `;
    this.container.appendChild(this.el);
  }

  _ref(name) {
    return this.el.querySelector(`[data-ref="${name}"]`);
  }

  _bindEvents() {
    // 閉じる
    this.el.querySelector('[data-action="close"]').addEventListener('click', () => this.close());

    // タブ切り替え
    this.el.querySelectorAll('.ma-modal-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        this.el.querySelectorAll('.ma-modal-tab').forEach(t => t.classList.remove('active'));
        this.el.querySelectorAll('.ma-modal-tab-content').forEach(c => c.classList.remove('active'));
        tab.classList.add('active');
        this.el.querySelector(`[data-tab-content="${tab.dataset.tab}"]`).classList.add('active');
        if (tab.dataset.tab === 'plugins') this._loadPlugins();
      });
    });

    // 設定保存
    this.el.querySelector('[data-action="save-settings"]').addEventListener('click', () => this._saveSettings());

    // 会議種別追加
    this.el.querySelector('[data-action="add-type"]').addEventListener('click', () => this._addType());

    // プロンプト追加
    this.el.querySelector('[data-action="add-prompt"]').addEventListener('click', () => this._addPrompt());

    // プラグイン追加
    this.el.querySelector('[data-action="add-plugin"]').addEventListener('click', () => this._addPlugin());
  }

  async _loadSettings() {
    try {
      const data = await this.api.getSettings();
      const s = data.settings;
      const settingFields = this.el.querySelectorAll('[data-setting]');
      settingFields.forEach(field => {
        const key = field.dataset.setting;
        if (field.type === 'checkbox') {
          field.checked = s[key] === 'true';
        } else {
          field.value = s[key] || '';
        }
      });
    } catch (e) {
      console.error('Failed to load settings:', e);
    }
  }

  async _saveSettings() {
    const settings = {};
    this.el.querySelectorAll('[data-setting]').forEach(field => {
      const key = field.dataset.setting;
      if (field.type === 'checkbox') {
        settings[key] = field.checked ? 'true' : 'false';
      } else {
        settings[key] = field.value;
      }
    });
    await this.api.saveSettings(settings);
    alert('設定を保存しました！\n\nリサーチ機能の設定は録音中でも即座に反映されます。');
  }

  async _renderMeetingTypes() {
    try {
      const data = await this.api.getMeetingTypes();
      const list = this._ref('meetingTypeList');
      list.innerHTML = '';

      data.meeting_types.forEach(t => {
        const item = document.createElement('div');
        item.style.cssText = 'padding:8px; border-bottom:1px solid rgba(255,255,255,0.1); display:flex; justify-content:space-between; cursor:pointer;';
        if (this.selectedTypeId === t.id) item.style.background = 'rgba(0,255,170,0.1)';

        const nameSpan = document.createElement('span');
        nameSpan.textContent = t.name;

        const delBtn = document.createElement('button');
        delBtn.className = 'ma-btn ma-btn-danger';
        delBtn.style.cssText = 'width:auto; padding:2px 8px;';
        delBtn.textContent = '\u00d7';
        delBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          this._deleteType(t.id);
        });

        item.appendChild(nameSpan);
        item.appendChild(delBtn);
        item.addEventListener('click', () => this._selectType(t));
        list.appendChild(item);
      });
    } catch (e) {
      console.error('Failed to load meeting types:', e);
    }
  }

  async _addType() {
    const input = this._ref('newTypeName');
    const name = input.value.trim();
    if (!name) return;
    await this.api.createMeetingType(name);
    input.value = '';
    this._renderMeetingTypes();
  }

  async _deleteType(id) {
    if (!confirm('削除しますか？')) return;
    await this.api.deleteMeetingType(id);
    if (this.selectedTypeId === id) {
      this.selectedTypeId = null;
      this._ref('promptForm').style.display = 'none';
      this._ref('promptsList').innerHTML = '';
    }
    this._renderMeetingTypes();
  }

  async _selectType(type) {
    this.selectedTypeId = type.id;
    this._ref('promptsHeader').textContent = `${type.name} のプロンプト`;
    this._ref('promptForm').style.display = 'flex';
    this._renderMeetingTypes();

    const data = await this.api.getPrompts(type.id);
    const list = this._ref('promptsList');
    list.innerHTML = '';

    data.prompts.forEach(p => {
      const item = document.createElement('div');
      item.style.cssText = 'background:rgba(255,255,255,0.05); padding:8px; margin-bottom:5px; border-radius:4px;';

      const header = document.createElement('div');
      header.style.cssText = 'display:flex; justify-content:space-between; margin-bottom:4px;';

      const triggerSpan = document.createElement('span');
      triggerSpan.style.cssText = 'color:var(--color-warning); font-weight:bold;';
      triggerSpan.textContent = p.trigger_condition;

      const delBtn = document.createElement('button');
      delBtn.className = 'ma-btn ma-btn-danger';
      delBtn.style.cssText = 'width:auto; padding:2px 5px; font-size:0.7rem;';
      delBtn.textContent = '削除';
      delBtn.addEventListener('click', () => this._deletePrompt(p.id));

      header.appendChild(triggerSpan);
      header.appendChild(delBtn);

      const body = document.createElement('div');
      body.style.cssText = 'font-size:0.8rem; opacity:0.8;';
      body.textContent = p.action_prompt;

      item.appendChild(header);
      item.appendChild(body);
      list.appendChild(item);
    });
  }

  async _addPrompt() {
    if (!this.selectedTypeId) return;
    const trigger = this._ref('newTrigger').value.trim();
    const action = this._ref('newAction').value.trim();
    if (!trigger || !action) return;

    await this.api.createPrompt(this.selectedTypeId, trigger, action);
    this._ref('newTrigger').value = '';
    this._ref('newAction').value = '';
    this._selectType({ id: this.selectedTypeId, name: this._ref('promptsHeader').textContent.replace(' のプロンプト', '') });
  }

  async _deletePrompt(id) {
    if (!confirm('削除しますか？')) return;
    await this.api.deletePrompt(id);
    if (this.selectedTypeId) {
      this._selectType({ id: this.selectedTypeId, name: this._ref('promptsHeader').textContent.replace(' のプロンプト', '') });
    }
  }

  async _loadPlugins() {
    try {
      const data = await this.api.getPlugins();
      this._renderPluginList(data.plugins || []);
    } catch (e) {
      console.error('Failed to load plugins:', e);
    }
  }

  _renderPluginList(plugins) {
    const container = this._ref('pluginList');
    if (plugins.length === 0) {
      container.innerHTML = '<div class="ma-empty-state" style="height:auto; padding:20px;">登録済みプラグインはありません</div>';
      return;
    }
    container.innerHTML = '';
    plugins.forEach(p => {
      const statusColor = p.enabled ? 'var(--color-success)' : 'var(--color-text-muted)';
      const item = document.createElement('div');
      item.style.cssText = 'display:flex; align-items:center; gap:10px; padding:10px; margin-bottom:8px; background:var(--color-surface-dim); border:1px solid var(--color-border); border-radius:4px;';

      const info = document.createElement('div');
      info.style.flex = '1';
      info.innerHTML = `
        <div style="font-weight:500;">${this._escapeHtml(p.name)}</div>
        <div class="ma-hint">${p.protocol}${p.endpoint ? ' &rarr; ' + this._escapeHtml(p.endpoint) : ''}</div>
        <div class="ma-hint" style="color:var(--color-text-muted);">Events: ${p.events.length === 0 ? '全イベント' : p.events.join(', ')}</div>
      `;

      const toggleBtn = document.createElement('button');
      toggleBtn.className = 'ma-btn';
      toggleBtn.style.cssText = `background:${statusColor}22; color:${statusColor}; border:1px solid ${statusColor}; padding:4px 12px; flex:0;`;
      toggleBtn.textContent = p.enabled ? 'ON' : 'OFF';
      toggleBtn.addEventListener('click', async () => {
        await this.api.updatePlugin(p.name, { enabled: !p.enabled });
        this._loadPlugins();
      });

      const delBtn = document.createElement('button');
      delBtn.className = 'ma-btn';
      delBtn.style.cssText = 'background:rgba(255,100,100,0.1); color:#ff6464; border:1px solid #ff6464; padding:4px 10px; flex:0;';
      delBtn.textContent = '削除';
      delBtn.addEventListener('click', async () => {
        if (!confirm(`プラグイン "${p.name}" を削除しますか？`)) return;
        await this.api.deletePlugin(p.name);
        this._loadPlugins();
      });

      item.appendChild(info);
      item.appendChild(toggleBtn);
      item.appendChild(delBtn);
      container.appendChild(item);
    });
  }

  async _addPlugin() {
    const name = this._ref('pluginName').value.trim();
    if (!name) { alert('名前を入力してください'); return; }

    const protocol = this._ref('pluginProtocol').value;
    const endpoint = this._ref('pluginEndpoint').value.trim();
    const eventCheckboxes = this._ref('pluginEvents').querySelectorAll('input[type=checkbox]:checked');
    const events = Array.from(eventCheckboxes).map(cb => cb.value);

    await this.api.createPlugin({ name, protocol, endpoint, events, enabled: true });

    this._ref('pluginName').value = '';
    this._ref('pluginEndpoint').value = '';
    this._ref('pluginEvents').querySelectorAll('input[type=checkbox]').forEach(cb => cb.checked = false);
    this._loadPlugins();
  }

  _escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }
}
