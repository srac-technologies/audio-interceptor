/**
 * HistoryModal - 履歴画面コンポーネント
 */
export class HistoryModal {
  /**
   * @param {HTMLElement} container
   * @param {import('../api/client.js').ApiClient} apiClient
   */
  constructor(container, apiClient) {
    this.container = container;
    this.api = apiClient;
    this._render();
    this._bindEvents();
  }

  open() {
    this.el.classList.add('open');
    this._loadSessions();
  }

  close() {
    this.el.classList.remove('open');
  }

  _render() {
    this.el = document.createElement('div');
    this.el.className = 'ma-modal';
    this.el.innerHTML = `
      <div class="ma-modal-content">
        <div class="ma-modal-header">
          <h2>履歴</h2>
          <button class="ma-close-btn" data-action="close">&times;</button>
        </div>
        <div style="display:flex; flex:1; gap:20px; overflow:hidden;">
          <div style="flex:1; overflow-y:auto; border-right:1px solid rgba(255,255,255,0.1); padding-right:10px;">
            <div data-ref="sessionList"></div>
          </div>
          <div style="flex:2; overflow-y:auto; padding:0 10px; display:flex; flex-direction:column;">
            <div style="display:flex; justify-content:flex-end; margin-bottom:10px;">
              <button data-ref="downloadBtn" class="ma-btn" style="background:var(--color-info); color:white; padding:8px 15px; display:none; flex:0; width:auto;">Docxでダウンロード</button>
            </div>
            <div data-ref="detailContent">
              <p style="text-align:center; opacity:0.5; margin-top:50px;">左側から会議を選択してください</p>
            </div>
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
    this.el.querySelector('[data-action="close"]').addEventListener('click', () => this.close());
  }

  async _loadSessions() {
    try {
      const data = await this.api.getHistory();
      const list = this._ref('sessionList');
      list.innerHTML = '';

      data.sessions.forEach(s => {
        const item = document.createElement('div');
        item.style.cssText = 'padding:10px; border-bottom:1px solid rgba(255,255,255,0.1); cursor:pointer;';
        item.innerHTML = `
          <div style="font-weight:bold; margin-bottom:4px;">${this._escapeHtml(s.title || 'Untitled')}</div>
          <div style="font-size:0.8rem; opacity:0.6;">${new Date(s.start_time).toLocaleString()}</div>
          <div style="font-size:0.8rem; color:var(--color-accent);">${this._escapeHtml(s.meeting_type_name || '')}</div>
        `;
        item.addEventListener('click', () => this._showDetail(s.id));
        list.appendChild(item);
      });
    } catch (e) {
      console.error('Failed to load history:', e);
    }
  }

  async _showDetail(sessionId) {
    try {
      const data = await this.api.getHistoryDetail(sessionId);
      const content = this._ref('detailContent');
      const dlBtn = this._ref('downloadBtn');

      dlBtn.style.display = 'block';
      dlBtn.onclick = () => window.open(this.api.getDocxDownloadUrl(sessionId));

      let html = '';

      // タイトル（編集可能）
      html += `
        <div data-ref="titleSection" style="display:flex; align-items:center; gap:10px; margin-bottom:20px; padding-bottom:15px; border-bottom:1px solid rgba(255,255,255,0.1);">
          <h2 data-ref="titleDisplay" style="flex:1; margin:0; cursor:pointer; color:var(--color-accent);" title="クリックで編集">${this._escapeHtml(data.session.title || 'Untitled')}</h2>
          <button data-action="edit-title" class="ma-btn" style="width:auto; padding:6px 12px; background:rgba(100,150,255,0.2); color:var(--color-mic); border:1px solid var(--color-mic); font-size:0.85rem; flex:0;">編集</button>
        </div>
        <div data-ref="titleEditForm" style="display:none; margin-bottom:20px; padding-bottom:15px; border-bottom:1px solid rgba(255,255,255,0.1);">
          <input type="text" class="ma-input" data-ref="editTitleInput" value="${this._escapeAttr(data.session.title || '')}" style="margin-bottom:8px;">
          <div style="display:flex; gap:8px;">
            <button data-action="save-title" class="ma-btn ma-btn-save" style="flex:1;">保存</button>
            <button data-action="cancel-title" class="ma-btn" style="flex:1; background:#666; color:white;">キャンセル</button>
          </div>
        </div>
      `;

      // サマリー
      if (data.session.summary) {
        html += `
          <div style="background:rgba(255,255,255,0.05); padding:15px; border-radius:8px; margin-bottom:20px;">
            <h3 style="margin-bottom:10px; color:var(--color-accent);">Summary</h3>
            <div style="white-space:pre-wrap; line-height:1.6;">${this._escapeHtml(data.session.summary)}</div>
          </div>
        `;
      }

      // ログ
      const allEvents = [
        ...data.transcripts.map(t => ({ ...t, _type: 'transcript' })),
        ...data.advices.map(a => ({ ...a, _type: 'advice' }))
      ].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));

      allEvents.forEach(e => {
        if (e._type === 'transcript') {
          const color = e.source === 'speaker' ? 'var(--color-accent)' : 'var(--color-mic)';
          html += `
            <div style="margin-bottom:10px; font-size:0.9rem;">
              <span style="opacity:0.5; font-size:0.8rem;">${new Date(e.timestamp).toLocaleTimeString()}</span>
              <span style="color:${color}; font-weight:bold; margin:0 5px;">${e.source.toUpperCase()}</span>
              <span>${this._escapeHtml(e.text)}</span>
            </div>
          `;
        } else {
          html += `
            <div class="ma-research-item" style="margin:15px 0;">
              <div class="ma-research-header" style="color:var(--color-warning);">Advice (${this._escapeHtml(e.trigger_condition)})</div>
              <div>${this._escapeHtml(e.advice_text)}</div>
            </div>
          `;
        }
      });

      content.innerHTML = html;

      // タイトル編集機能
      this._bindTitleEdit(sessionId);
    } catch (e) {
      console.error('Failed to load session detail:', e);
    }
  }

  _bindTitleEdit(sessionId) {
    const titleDisplay = this._ref('titleDisplay');
    const editBtn = this.el.querySelector('[data-action="edit-title"]');
    const editForm = this._ref('titleEditForm');
    const editInput = this._ref('editTitleInput');
    const titleSection = this._ref('titleSection');

    const showEdit = () => {
      titleSection.style.display = 'none';
      editForm.style.display = 'block';
      editInput.focus();
      editInput.select();
    };

    const hideEdit = () => {
      titleSection.style.display = 'flex';
      editForm.style.display = 'none';
    };

    const saveTitle = async () => {
      const newTitle = editInput.value.trim();
      if (!newTitle) { alert('タイトルを入力してください'); return; }
      try {
        const result = await this.api.updateSessionTitle(sessionId, newTitle);
        if (result.success) {
          titleDisplay.textContent = newTitle;
          hideEdit();
          this._loadSessions();
        }
      } catch (e) {
        alert('タイトル更新に失敗しました');
      }
    };

    titleDisplay?.addEventListener('click', showEdit);
    editBtn?.addEventListener('click', showEdit);
    this.el.querySelector('[data-action="save-title"]')?.addEventListener('click', saveTitle);
    this.el.querySelector('[data-action="cancel-title"]')?.addEventListener('click', hideEdit);
    editInput?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); saveTitle(); }
      else if (e.key === 'Escape') { e.preventDefault(); hideEdit(); }
    });
  }

  _escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
  }

  _escapeAttr(str) {
    return (str || '').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
}
